"""Fluxo do agente Questor: snapshot → análise → alerta por e-mail.

O snapshot pode vir do scraper Playwright (``portal.fetch_questor_snapshot``) ou
ser injetado (arquivo JSON no CLI, ou fixture nos testes). A análise é offline; o
alerta só dispara quando há pendência nova (dedup por ``dedup_key`` em estado
persistido), evitando reenviar o mesmo problema a cada execução.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from classificacao_procons.google_auth import GoogleAuthError, has_gmail_send_access
from classificacao_procons.questor.analise import DEFAULT_WARN_WITHIN_DAYS, analyze_snapshot
from classificacao_procons.questor.models import (
    FiscalIssue,
    QuestorAnalysis,
    QuestorSnapshot,
)
from classificacao_procons.questor.notifier import (
    GmailSender,
    GmailSenderError,
    build_alert_email,
)
from classificacao_procons.questor.policy import (
    DEFAULT_CAIXA_MODE,
    DEFAULT_UNREAD_WINDOW_DAYS,
    select_actionable_messages,
    unread_summary,
)

DEFAULT_STATE_PATH = Path("data/questor-alerted.json")

SnapshotProvider = Callable[["QuestorPipelineOptions"], QuestorSnapshot]


class QuestorPipelineError(RuntimeError):
    """Erro geral no pipeline do agente Questor."""


@dataclass(frozen=True)
class QuestorPipelineOptions:
    recipients: tuple[str, ...] = ()
    cc: tuple[str, ...] = ()
    sender: str | None = None
    warn_within_days: int = DEFAULT_WARN_WITHIN_DAYS
    caixa_mode: str = DEFAULT_CAIXA_MODE
    unread_window_days: int = DEFAULT_UNREAD_WINDOW_DAYS
    dry_run: bool = False
    only_new: bool = True
    state_path: Path = DEFAULT_STATE_PATH
    token_path: str = "credentials/gmail-token.json"
    # Portal (scraping) — opcional; só usado quando o snapshot não é injetado.
    portal_url: str | None = None
    portal_login: str | None = None
    portal_password: str | None = None
    empresa: str | None = None
    cnpj: str | None = None
    headless: bool = True
    refresh_certidoes: bool = False
    refresh_wait_seconds: int = 120
    # Credenciais no Monday (usadas quando login/senha do portal não vêm nas opções).
    monday_api_token: str | None = None


@dataclass(frozen=True)
class QuestorPipelineResult:
    status: str
    analysis: QuestorAnalysis | None = None
    new_issues: tuple[FiscalIssue, ...] = field(default_factory=tuple)
    alert_sent: bool = False
    alert_recipients: tuple[str, ...] = ()
    message_id: str | None = None
    error: str | None = None


def _load_alerted_keys(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(key) for key in data.get("alerted_keys", [])}


def _save_alerted_keys(state_path: Path, keys: set[str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"alerted_keys": sorted(keys)}
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_snapshot(
    options: QuestorPipelineOptions,
    *,
    snapshot: QuestorSnapshot | None,
    snapshot_provider: SnapshotProvider | None,
) -> QuestorSnapshot:
    if snapshot is not None:
        return snapshot
    provider = snapshot_provider or _default_portal_provider
    return provider(options)


def _resolve_portal_login(options: QuestorPipelineOptions) -> tuple[str, str, str]:
    """Resolve (portal_url, login, senha): das opções ou do board Acessos do Monday."""
    login = options.portal_login
    password = options.portal_password
    portal_url = options.portal_url

    if not login or not password:
        from classificacao_procons.questor.credentials import (
            QuestorCredentialsError,
            resolve_questor_credentials,
        )

        try:
            credential = resolve_questor_credentials(api_token=options.monday_api_token)
        except QuestorCredentialsError as exc:
            raise QuestorPipelineError(str(exc)) from exc
        login = login or credential.login
        password = password or credential.password
        portal_url = portal_url or credential.portal_url

    if not portal_url or not login or not password:
        raise QuestorPipelineError(
            "Credenciais do portal Questor ausentes (portal_url/login/password) e "
            "nenhum snapshot injetado.",
        )
    return portal_url, login, password


def _default_portal_provider(options: QuestorPipelineOptions) -> QuestorSnapshot:
    # Import tardio: Playwright só é necessário para o scraping real.
    from classificacao_procons.questor.portal import (
        QuestorPortalError,
        QuestorPortalOptions,
        fetch_questor_snapshot,
    )

    portal_url, login, password = _resolve_portal_login(options)
    try:
        return fetch_questor_snapshot(
            QuestorPortalOptions(
                portal_url=portal_url,
                login=login,
                password=password,
                empresa=options.empresa,
                cnpj=options.cnpj,
                headless=options.headless,
                refresh_stale_certidoes=options.refresh_certidoes,
                refresh_wait_seconds=options.refresh_wait_seconds,
            ),
        )
    except QuestorPortalError as exc:
        raise QuestorPipelineError(str(exc)) from exc


def run_questor_refresh(options: QuestorPipelineOptions) -> tuple[tuple[int, ...], int]:
    """Dispara a recaptura das certidões não regulares (fase de gatilho).

    Retorna ``(ids_recapturados, quantidade_aceita)``. A nova situação chega
    depois (assíncrono); rode a leitura/alerta num segundo momento.
    """
    from classificacao_procons.questor.portal import (
        QuestorPortalError,
        QuestorPortalOptions,
        refresh_stale_certidoes,
    )

    portal_url, login, password = _resolve_portal_login(options)
    try:
        result = refresh_stale_certidoes(
            QuestorPortalOptions(
                portal_url=portal_url,
                login=login,
                password=password,
                headless=options.headless,
            ),
        )
    except QuestorPortalError as exc:
        raise QuestorPipelineError(str(exc)) from exc
    return result.stale_ids, result.triggered


def run_questor_check(
    options: QuestorPipelineOptions,
    *,
    snapshot: QuestorSnapshot | None = None,
    snapshot_provider: SnapshotProvider | None = None,
    today: date | None = None,
) -> QuestorPipelineResult:
    """Coleta o snapshot, analisa e alerta o time se houver pendência nova."""
    resolved = _resolve_snapshot(
        options,
        snapshot=snapshot,
        snapshot_provider=snapshot_provider,
    )

    # Política de caixa postal: analisa só as mensagens acionáveis (o backlog
    # completo vira uma nota de contexto no e-mail).
    actionable = select_actionable_messages(
        resolved.mensagens,
        mode=options.caixa_mode,
        window_days=options.unread_window_days,
        today=today,
    )
    backlog_note = unread_summary(resolved.mensagens)
    filtered = replace(resolved, mensagens=tuple(actionable))

    analysis = analyze_snapshot(
        filtered,
        today=today,
        warn_within_days=options.warn_within_days,
    )

    alerted_keys = _load_alerted_keys(options.state_path)
    if options.only_new:
        new_issues = tuple(
            issue for issue in analysis.issues if issue.dedup_key not in alerted_keys
        )
    else:
        new_issues = analysis.issues

    if not analysis.has_problems:
        return QuestorPipelineResult(status="ok", analysis=analysis)

    if not new_issues:
        return QuestorPipelineResult(
            status="no_new_issues",
            analysis=analysis,
        )

    if options.dry_run:
        return QuestorPipelineResult(
            status="dry_run",
            analysis=analysis,
            new_issues=new_issues,
            alert_recipients=tuple(options.recipients),
        )

    if not options.recipients:
        raise QuestorPipelineError("Nenhum destinatário configurado para o alerta fiscal.")

    if not has_gmail_send_access(options.token_path):
        raise QuestorPipelineError(
            "Token Gmail sem permissão de envio. Reautorize com: procon-email auth",
        )

    alert_analysis = QuestorAnalysis(snapshot=filtered, issues=new_issues)
    email = build_alert_email(
        alert_analysis,
        to=list(options.recipients),
        cc=list(options.cc),
        extra_note=backlog_note,
    )
    try:
        sender = GmailSender.from_credentials(token_path=options.token_path)
        message_id = sender.send(email, sender=options.sender)
    except (GmailSenderError, GoogleAuthError) as exc:
        raise QuestorPipelineError(str(exc)) from exc

    _save_alerted_keys(
        options.state_path,
        alerted_keys | {issue.dedup_key for issue in new_issues},
    )

    return QuestorPipelineResult(
        status="alert_sent",
        analysis=analysis,
        new_issues=new_issues,
        alert_sent=True,
        alert_recipients=tuple(options.recipients),
        message_id=message_id,
    )
