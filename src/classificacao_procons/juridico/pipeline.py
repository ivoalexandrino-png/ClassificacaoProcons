"""Fluxo automático do jurídico: intimação → triagem → Monday → eventos."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from classificacao_procons.email.gmail import GmailClientError
from classificacao_procons.google_auth import (
    GoogleAuthError,
    has_gmail_modify_access,
    has_valid_token,
)
from classificacao_procons.juridico.datajud import (
    DataJudError,
    fetch_case_movements,
    get_api_key_from_env,
)
from classificacao_procons.juridico.events import (
    DEFAULT_EVENTS_PATH,
    EVENT_ATUALIZAR_CONTINGENCIA,
    EVENT_ELABORAR_PECA,
    AgentEvent,
    emit_event,
)
from classificacao_procons.juridico.gmail import GmailJuridicoFetcher
from classificacao_procons.juridico.models import (
    CaseMovement,
    JudicialNotificationEmail,
    ParsedIntimacao,
    ProcessedIntimacao,
    Providencia,
)
from classificacao_procons.juridico.monday import MondayClientError, register_providencia
from classificacao_procons.juridico.parser import (
    IntimacaoParseError,
    parse_judicial_notification_body,
)
from classificacao_procons.juridico.providencias import affects_contingency, classify_providencia

DEFAULT_STATE_PATH = Path("data/juridico-processed.json")


class JuridicoPipelineError(RuntimeError):
    """Erro geral no pipeline do agente jurídico."""


@dataclass(frozen=True)
class JuridicoPipelineOptions:
    max_results: int = 20
    state_path: Path = DEFAULT_STATE_PATH
    events_path: Path = DEFAULT_EVENTS_PATH
    mark_read: bool = True
    dry_run: bool = False
    credentials_path: str = "credentials/gmail-oauth.json"
    token_path: str = "credentials/gmail-token.json"
    monday_api_token: str | None = None
    monday_board_name: str | None = None
    monday_group_name: str | None = None
    register_on_monday: bool = True
    consult_datajud: bool = True
    datajud_limit: int = 5


def _load_processed_messages(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(item) for item in data.get("message_ids", [])}


def _save_processed_messages(state_path: Path, message_ids: set[str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"message_ids": sorted(message_ids)}
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_movements_if_configured(
    intimacao: ParsedIntimacao,
    *,
    options: JuridicoPipelineOptions,
) -> tuple[list[CaseMovement], str | None]:
    """Consulta o DataJud quando há chave; falha na consulta não bloqueia o fluxo."""
    if not options.consult_datajud or not get_api_key_from_env():
        return [], None
    try:
        movements = fetch_case_movements(
            intimacao.process_number,
            limit=options.datajud_limit,
        )
    except DataJudError as exc:
        return [], str(exc)
    return movements, None


def _register_on_monday_if_configured(
    *,
    intimacao: ParsedIntimacao,
    providencia: Providencia,
    message_id: str,
    options: JuridicoPipelineOptions,
) -> tuple[str | None, str | None]:
    if not options.register_on_monday or not providencia.requires_action:
        return None, None
    try:
        registration = register_providencia(
            intimacao=intimacao,
            providencia=providencia,
            message_id=message_id,
            api_token=options.monday_api_token,
            board_name=options.monday_board_name,
            group_name=options.monday_group_name,
        )
    except MondayClientError as exc:
        return None, str(exc)
    if registration is None:
        return None, None
    return registration.item_url, None


def _emit_handoff_events(
    *,
    intimacao: ParsedIntimacao,
    providencia: Providencia,
    movements: list[CaseMovement],
    monday_item_url: str | None,
    options: JuridicoPipelineOptions,
) -> list[str]:
    """Emite eventos para os agentes futuros de peças e de contingência."""
    emitted: list[str] = []
    due_date = providencia.due_date.isoformat() if providencia.due_date else None

    if providencia.requires_action and providencia.requires_legal_document:
        emit_event(
            AgentEvent(
                event_type=EVENT_ELABORAR_PECA,
                process_number=intimacao.process_number,
                action_type=providencia.action_type,
                due_date=due_date,
                monday_item_url=monday_item_url,
                payload={
                    "notification_type": intimacao.notification_type,
                    "tribunal": intimacao.tribunal,
                    "court_unit": intimacao.court_unit,
                    "summary": intimacao.summary,
                },
            ),
            events_path=options.events_path,
        )
        emitted.append(EVENT_ELABORAR_PECA)

    movements_payload = [
        {
            "name": movement.movement_name,
            "code": movement.movement_code,
            "datetime": (
                movement.movement_datetime.isoformat() if movement.movement_datetime else None
            ),
        }
        for movement in movements
    ]
    movement_text = " ".join(movement.movement_name for movement in movements)
    emit_event(
        AgentEvent(
            event_type=EVENT_ATUALIZAR_CONTINGENCIA,
            process_number=intimacao.process_number,
            action_type=providencia.action_type,
            due_date=due_date,
            monday_item_url=monday_item_url,
            payload={
                "notification_type": intimacao.notification_type,
                "summary": intimacao.summary,
                "movements": movements_payload,
                "affects_contingency": (
                    providencia.affects_contingency or affects_contingency(movement_text)
                ),
            },
        ),
        events_path=options.events_path,
    )
    emitted.append(EVENT_ATUALIZAR_CONTINGENCIA)
    return emitted


def _error_result(
    notification: JudicialNotificationEmail,
    *,
    error: str,
    process_number: str = "",
) -> ProcessedIntimacao:
    return ProcessedIntimacao(
        status="error",
        message_id=notification.message_id,
        process_number=process_number,
        notification_type="",
        action_type="",
        requires_action=False,
        error=error,
    )


def _process_notification(
    notification: JudicialNotificationEmail,
    *,
    options: JuridicoPipelineOptions,
    processed_messages: set[str],
    fetcher: GmailJuridicoFetcher,
) -> ProcessedIntimacao:
    intimacao = parse_judicial_notification_body(
        text=notification.body_text,
        subject=notification.subject,
    )
    providencia = classify_providencia(intimacao, base_date=notification.received_at.date())

    base_result = ProcessedIntimacao(
        status="dry_run" if options.dry_run else "success",
        message_id=notification.message_id,
        process_number=intimacao.process_number,
        notification_type=intimacao.notification_type,
        action_type=providencia.action_type,
        requires_action=providencia.requires_action,
        due_date=providencia.due_date,
        hearing_datetime=providencia.hearing_datetime,
        tribunal=intimacao.tribunal,
        court_unit=intimacao.court_unit,
        summary=intimacao.summary,
    )

    if options.dry_run:
        return base_result

    movements, datajud_error = _fetch_movements_if_configured(intimacao, options=options)

    monday_item_url, monday_error = _register_on_monday_if_configured(
        intimacao=intimacao,
        providencia=providencia,
        message_id=notification.message_id,
        options=options,
    )

    events_emitted = _emit_handoff_events(
        intimacao=intimacao,
        providencia=providencia,
        movements=movements,
        monday_item_url=monday_item_url,
        options=options,
    )

    processed_messages.add(notification.message_id)
    _save_processed_messages(options.state_path, processed_messages)

    if options.mark_read and has_gmail_modify_access(options.token_path):
        fetcher.mark_as_read(notification.message_id)

    return replace(
        base_result,
        monday_item_url=monday_item_url,
        monday_error=monday_error,
        events_emitted=events_emitted,
        error=datajud_error,
    )


def process_new_intimacoes(
    options: JuridicoPipelineOptions | None = None,
) -> list[ProcessedIntimacao]:
    """Processa intimações não lidas: triagem, Monday e eventos de handoff."""
    options = options or JuridicoPipelineOptions()

    if not options.dry_run and not has_valid_token(options.token_path):
        raise JuridicoPipelineError("Google não conectado. Rode: procon-email auth")

    try:
        fetcher = GmailJuridicoFetcher.from_credentials(
            credentials_path=options.credentials_path,
            token_path=options.token_path,
        )
        notifications = fetcher.list_unread_notifications(max_results=options.max_results)
    except (GmailClientError, GoogleAuthError) as exc:
        raise JuridicoPipelineError(str(exc)) from exc

    processed_messages = _load_processed_messages(options.state_path)
    results: list[ProcessedIntimacao] = []

    for notification in notifications:
        if notification.message_id in processed_messages:
            results.append(
                ProcessedIntimacao(
                    status="skipped_duplicate",
                    message_id=notification.message_id,
                    process_number="",
                    notification_type="",
                    action_type="",
                    requires_action=False,
                    error="Intimação já processada anteriormente.",
                ),
            )
            continue

        try:
            result = _process_notification(
                notification,
                options=options,
                processed_messages=processed_messages,
                fetcher=fetcher,
            )
        except IntimacaoParseError as exc:
            result = _error_result(notification, error=str(exc))
        except GmailClientError as exc:
            result = _error_result(notification, error=str(exc))

        results.append(result)

    return results
