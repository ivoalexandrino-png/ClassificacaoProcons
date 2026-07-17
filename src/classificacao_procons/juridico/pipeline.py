"""Fluxo automático do jurídico: intimação → processo → análise → Monday → eventos."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from classificacao_procons.email.gmail import GmailClientError
from classificacao_procons.google_auth import (
    GoogleAuthError,
    has_gmail_modify_access,
    has_valid_token,
)
from classificacao_procons.juridico.analise import analyze_case
from classificacao_procons.juridico.comunica import ComunicaError, fetch_case_communications
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
    CaseAnalysis,
    CaseCommunication,
    CaseMovement,
    JudicialNotificationEmail,
    ParsedIntimacao,
    ProcessedIntimacao,
    Providencia,
)
from classificacao_procons.juridico.monday import (
    MondayClientError,
    register_audiencia,
    register_providencia,
)
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
    consult_comunica: bool = True
    comunica_limit: int = 5


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


def _fetch_communications_if_configured(
    intimacao: ParsedIntimacao,
    *,
    options: JuridicoPipelineOptions,
) -> tuple[list[CaseCommunication], str | None]:
    """Busca o teor no Domicílio Judicial (Comunica); falha não bloqueia o fluxo."""
    if not options.consult_comunica:
        return [], None
    try:
        communications = fetch_case_communications(
            intimacao.process_number,
            limit=options.comunica_limit,
        )
    except ComunicaError as exc:
        return [], str(exc)
    return communications, None


def _enrich_with_communications(
    intimacao: ParsedIntimacao,
    *,
    subject: str,
    email_text: str,
    communications: list[CaseCommunication],
) -> ParsedIntimacao:
    """Reprocessa a intimação incluindo o teor oficial — melhora tipo, prazo e vara."""
    if not communications:
        return intimacao
    teor_blocks = "\n\n".join(
        f"TEOR DA COMUNICAÇÃO OFICIAL:\n{communication.text}"
        for communication in communications
    )
    try:
        return parse_judicial_notification_body(
            text=f"{email_text}\n\n{teor_blocks}",
            subject=subject,
        )
    except IntimacaoParseError:
        return intimacao


def _register_on_monday_if_configured(
    *,
    intimacao: ParsedIntimacao,
    providencia: Providencia,
    analysis: CaseAnalysis,
    message_id: str,
    options: JuridicoPipelineOptions,
) -> tuple[str | None, str | None, str | None]:
    """Registra o prazo no board "prazos" e, havendo audiência, no board "audiências".

    Retorna (url do item de prazo, url do item de audiência, erros combinados).
    """
    if not options.register_on_monday:
        return None, None, None

    prazo_url: str | None = None
    audiencia_url: str | None = None
    errors: list[str] = []

    if providencia.requires_action:
        try:
            registration = register_providencia(
                intimacao=intimacao,
                providencia=providencia,
                message_id=message_id,
                analysis=analysis.text,
                api_token=options.monday_api_token,
                board_name=options.monday_board_name,
                group_name=options.monday_group_name,
            )
            prazo_url = registration.item_url if registration else None
        except MondayClientError as exc:
            errors.append(f"prazos: {exc}")

    if providencia.hearing_datetime is not None:
        try:
            registration = register_audiencia(
                intimacao=intimacao,
                providencia=providencia,
                message_id=message_id,
                analysis=analysis.text,
                api_token=options.monday_api_token,
            )
            audiencia_url = registration.item_url if registration else None
        except MondayClientError as exc:
            errors.append(f"audiencias: {exc}")

    return prazo_url, audiencia_url, "; ".join(errors) or None


def _emit_handoff_events(
    *,
    intimacao: ParsedIntimacao,
    providencia: Providencia,
    analysis: CaseAnalysis,
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
                    "analysis": analysis.text,
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
                "analysis": analysis.text,
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


def _needs_review_result(
    notification: JudicialNotificationEmail,
    *,
    reason: str,
) -> ProcessedIntimacao:
    """E-mail judicial sem dados extraíveis (ex.: PROJUDI sem número CNJ no corpo).

    Fica não lido na caixa e marcado para revisão manual, sem derrubar a execução.
    """
    return ProcessedIntimacao(
        status="needs_review",
        message_id=notification.message_id,
        process_number="",
        notification_type="",
        action_type="",
        requires_action=True,
        summary=f"{notification.subject} — de {notification.sender}",
        error=reason,
    )


def _process_notification(
    notification: JudicialNotificationEmail,
    *,
    options: JuridicoPipelineOptions,
    processed_messages: set[str],
    fetcher: GmailJuridicoFetcher,
) -> ProcessedIntimacao:
    # 1. E-mail (direto do tribunal, DJE ou encaminhado do e-mail pessoal)
    intimacao = parse_judicial_notification_body(
        text=notification.body_text,
        subject=notification.subject,
    )

    if options.dry_run:
        providencia = classify_providencia(intimacao, base_date=notification.received_at.date())
        return ProcessedIntimacao(
            status="dry_run",
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

    # 2. Entrar no processo: teor oficial (Domicílio Judicial) + andamentos (DataJud)
    communications, comunica_error = _fetch_communications_if_configured(
        intimacao,
        options=options,
    )
    intimacao = _enrich_with_communications(
        intimacao,
        subject=notification.subject,
        email_text=notification.body_text,
        communications=communications,
    )
    movements, datajud_error = _fetch_movements_if_configured(intimacao, options=options)

    # 3. Triagem + entendimento caso a caso
    providencia = classify_providencia(intimacao, base_date=notification.received_at.date())
    analysis = analyze_case(
        intimacao=intimacao,
        providencia=providencia,
        communications=communications,
        movements=movements,
    )

    # 4. Monday (caminho final) + eventos para os agentes futuros
    monday_item_url, monday_audiencia_url, monday_error = _register_on_monday_if_configured(
        intimacao=intimacao,
        providencia=providencia,
        analysis=analysis,
        message_id=notification.message_id,
        options=options,
    )

    events_emitted = _emit_handoff_events(
        intimacao=intimacao,
        providencia=providencia,
        analysis=analysis,
        movements=movements,
        monday_item_url=monday_item_url,
        options=options,
    )

    processed_messages.add(notification.message_id)
    _save_processed_messages(options.state_path, processed_messages)

    if options.mark_read and has_gmail_modify_access(options.token_path):
        fetcher.mark_as_read(notification.message_id)

    lookup_errors = "; ".join(error for error in (comunica_error, datajud_error) if error)
    return ProcessedIntimacao(
        status="success",
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
        analysis=analysis.text,
        analysis_source=analysis.source,
        communications_count=len(communications),
        monday_item_url=monday_item_url,
        monday_audiencia_url=monday_audiencia_url,
        monday_error=monday_error,
        events_emitted=events_emitted,
        error=lookup_errors or None,
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
            result = _needs_review_result(notification, reason=str(exc))
        except GmailClientError as exc:
            result = _error_result(notification, error=str(exc))

        results.append(result)

    return results
