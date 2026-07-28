"""Pipeline: e-mail Interação do Consumidor → Monday (update) + portal."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from classificacao_procons.email.attachments import list_message_attachments
from classificacao_procons.email.gmail import GmailClientError, GmailProconFetcher
from classificacao_procons.google_auth import has_gmail_modify_access, has_valid_token
from classificacao_procons.models import ProconNotificationEmail
from classificacao_procons.monday.client import (
    DEFAULT_BOARD_NAME,
    MondayClientError,
    create_item_update,
    find_item_id_by_protocol,
    get_api_token_from_env,
)
from classificacao_procons.portal import PortalFetchOptions, ProconPortalError
from classificacao_procons.portal.interactions import fetch_consumer_interactions

DEFAULT_INTERACTION_STATE_PATH = Path("data/processed-interactions.json")

INTERACTION_MENTION_EMAILS: tuple[str, ...] = (
    "walquiria.marquart@b4a.com.br",
    "manu@b4a.com.br",
)


class ConsumerInteractionPipelineError(RuntimeError):
    """Erro no fluxo de interação do consumidor."""


@dataclass(frozen=True)
class PendingConsumerInteraction:
    message_id: str
    protocol_number: str
    access_code: str | None
    received_at: str
    subject: str
    email_snippet: str | None


@dataclass(frozen=True)
class ProcessedConsumerInteraction:
    status: str
    message_id: str
    protocol_number: str
    monday_item_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ConsumerInteractionPipelineOptions:
    max_results: int = 20
    state_path: Path = DEFAULT_INTERACTION_STATE_PATH
    mark_read: bool = True
    dry_run: bool = False
    credentials_path: str = "credentials/gmail-oauth.json"
    token_path: str = "credentials/gmail-token.json"
    monday_api_token: str | None = None
    monday_board_name: str = DEFAULT_BOARD_NAME
    fetch_portal: bool = True
    download_dir: Path = Path("downloads")


def _load_state(state_path: Path) -> tuple[set[str], list[PendingConsumerInteraction]]:
    if not state_path.exists():
        return set(), []
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set(), []

    message_ids = {str(item) for item in data.get("processed_message_ids", [])}
    pending_raw = data.get("pending", [])
    pending: list[PendingConsumerInteraction] = []
    for entry in pending_raw:
        if not isinstance(entry, dict):
            continue
        protocol = str(entry.get("protocol_number", "")).strip()
        message_id = str(entry.get("message_id", "")).strip()
        if not protocol or not message_id:
            continue
        pending.append(
            PendingConsumerInteraction(
                message_id=message_id,
                protocol_number=protocol,
                access_code=entry.get("access_code") or None,
                received_at=str(entry.get("received_at", "")),
                subject=str(entry.get("subject", "")),
                email_snippet=entry.get("email_snippet"),
            ),
        )
    return message_ids, pending


def _save_state(
    state_path: Path,
    *,
    processed_message_ids: set[str],
    pending: list[PendingConsumerInteraction],
) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "processed_message_ids": sorted(processed_message_ids),
        "pending": [
            {
                "message_id": item.message_id,
                "protocol_number": item.protocol_number,
                "access_code": item.access_code,
                "received_at": item.received_at,
                "subject": item.subject,
                "email_snippet": item.email_snippet,
            }
            for item in pending
        ],
    }
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_interaction_update_body(
    *,
    protocol_number: str,
    email_subject: str,
    consumer_messages: tuple[str, ...],
    portal_attachment_labels: tuple[str, ...],
    email_attachment_names: tuple[str, ...],
) -> str:
    """Monta texto do update no Monday com menções fixas."""
    mentions = " ".join(f"@{email}" for email in INTERACTION_MENTION_EMAILS)
    lines = [
        f"{mentions}",
        "",
        "Nova interação do consumidor no Procon-SP",
        f"Protocolo: {protocol_number}",
        f"Assunto do e-mail: {email_subject}",
        "",
    ]
    if consumer_messages:
        lines.append("Mensagens do consumidor (portal):")
        for index, message in enumerate(consumer_messages, start=1):
            lines.append(f"{index}. {message}")
        lines.append("")
    if portal_attachment_labels or email_attachment_names:
        lines.append("Anexos:")
        for label in portal_attachment_labels:
            lines.append(f"- {label} (portal)")
        for name in email_attachment_names:
            lines.append(f"- {name} (e-mail)")
        lines.append("")
    if not consumer_messages and not portal_attachment_labels and not email_attachment_names:
        lines.append(
            "Conteúdo detalhado não extraído automaticamente; "
            "verifique o portal na aba Interações & Respostas.",
        )
    return "\n".join(lines).strip()


def _resolve_monday_token(options: ConsumerInteractionPipelineOptions) -> str | None:
    if options.monday_api_token:
        return options.monday_api_token
    return get_api_token_from_env()


def _enqueue_pending(
    pending: list[PendingConsumerInteraction],
    entry: PendingConsumerInteraction,
) -> list[PendingConsumerInteraction]:
    without_dup = [item for item in pending if item.message_id != entry.message_id]
    return [*without_dup, entry]


def _post_monday_interaction(
    *,
    api_token: str,
    board_name: str,
    protocol_number: str,
    body: str,
) -> str:
    item_id = find_item_id_by_protocol(
        api_token=api_token,
        protocol_number=protocol_number,
        board_name=board_name,
    )
    if item_id is None:
        raise MondayClientError(
            f"Item Monday não encontrado para o protocolo {protocol_number}.",
        )
    create_item_update(api_token=api_token, item_id=item_id, body=body)
    return item_id


def _process_single_interaction(
    notification: ProconNotificationEmail,
    *,
    options: ConsumerInteractionPipelineOptions,
    processed_message_ids: set[str],
    pending: list[PendingConsumerInteraction],
    fetcher: GmailProconFetcher,
) -> tuple[ProcessedConsumerInteraction, set[str], list[PendingConsumerInteraction]]:
    protocol = notification.protocol_number or ""
    if not protocol:
        return (
            ProcessedConsumerInteraction(
                status="error",
                message_id=notification.message_id,
                protocol_number="",
                error="Protocolo ausente na notificação.",
            ),
            processed_message_ids,
            pending,
        )

    if notification.message_id in processed_message_ids:
        return (
            ProcessedConsumerInteraction(
                status="skipped_duplicate",
                message_id=notification.message_id,
                protocol_number=protocol,
            ),
            processed_message_ids,
            pending,
        )

    if options.dry_run:
        return (
            ProcessedConsumerInteraction(
                status="dry_run",
                message_id=notification.message_id,
                protocol_number=protocol,
            ),
            processed_message_ids,
            pending,
        )

    api_token = _resolve_monday_token(options)
    if not api_token:
        return (
            ProcessedConsumerInteraction(
                status="error",
                message_id=notification.message_id,
                protocol_number=protocol,
                error="MONDAY_API_TOKEN não configurado.",
            ),
            processed_message_ids,
            pending,
        )

    email_attachment_names: tuple[str, ...] = ()
    try:
        payload = fetcher.fetch_message_payload(notification.message_id)
        email_attachment_names = tuple(
            attachment.filename for attachment in list_message_attachments(payload)
        )
    except GmailClientError:
        email_attachment_names = ()

    consumer_message_bodies: tuple[str, ...] = ()
    portal_attachment_labels: tuple[str, ...] = ()
    if options.fetch_portal and notification.access_code:
        try:
            portal_data = fetch_consumer_interactions(
                PortalFetchOptions(
                    access_code=notification.access_code,
                    download_dir=options.download_dir,
                ),
                protocol_hint=protocol,
            )
            consumer_message_bodies = tuple(message.body for message in portal_data.messages)
            portal_attachment_labels = portal_data.attachment_labels
        except ProconPortalError:
            consumer_message_bodies = ()
            portal_attachment_labels = ()

    body = build_interaction_update_body(
        protocol_number=protocol,
        email_subject=notification.subject,
        consumer_messages=consumer_message_bodies,
        portal_attachment_labels=portal_attachment_labels,
        email_attachment_names=email_attachment_names,
    )

    try:
        item_id = _post_monday_interaction(
            api_token=api_token,
            board_name=options.monday_board_name,
            protocol_number=protocol,
            body=body,
        )
    except MondayClientError as exc:
        if "não encontrado" in str(exc).lower():
            from classificacao_procons.pa_standalone_registry import (
                ensure_pa_monday_item_for_protocol,
            )

            try:
                ensure_pa_monday_item_for_protocol(
                    pa_protocol=protocol,
                    api_token=api_token,
                    board_name=options.monday_board_name,
                    fetcher=fetcher,
                    pa_opened_on=notification.received_at.date(),
                )
                item_id = _post_monday_interaction(
                    api_token=api_token,
                    board_name=options.monday_board_name,
                    protocol_number=protocol,
                    body=body,
                )
            except MondayClientError as register_exc:
                pending_entry = PendingConsumerInteraction(
                    message_id=notification.message_id,
                    protocol_number=protocol,
                    access_code=notification.access_code or None,
                    received_at=notification.received_at.isoformat(),
                    subject=notification.subject,
                    email_snippet=notification.raw_snippet,
                )
                new_pending = _enqueue_pending(pending, pending_entry)
                return (
                    ProcessedConsumerInteraction(
                        status="pending_monday_item",
                        message_id=notification.message_id,
                        protocol_number=protocol,
                        error=str(register_exc),
                    ),
                    processed_message_ids,
                    new_pending,
                )

            processed_message_ids = set(processed_message_ids)
            processed_message_ids.add(notification.message_id)
            new_pending = [item for item in pending if item.message_id != notification.message_id]
            if options.mark_read and has_gmail_modify_access(options.token_path):
                fetcher.mark_as_read(notification.message_id)
            return (
                ProcessedConsumerInteraction(
                    status="success",
                    message_id=notification.message_id,
                    protocol_number=protocol,
                    monday_item_id=item_id,
                ),
                processed_message_ids,
                new_pending,
            )
        return (
            ProcessedConsumerInteraction(
                status="error",
                message_id=notification.message_id,
                protocol_number=protocol,
                error=str(exc),
            ),
            processed_message_ids,
            pending,
        )

    processed_message_ids = set(processed_message_ids)
    processed_message_ids.add(notification.message_id)
    new_pending = [item for item in pending if item.message_id != notification.message_id]

    if options.mark_read and has_gmail_modify_access(options.token_path):
        fetcher.mark_as_read(notification.message_id)

    return (
        ProcessedConsumerInteraction(
            status="success",
            message_id=notification.message_id,
            protocol_number=protocol,
            monday_item_id=item_id,
        ),
        processed_message_ids,
        new_pending,
    )


def flush_pending_interactions_for_protocol(
    protocol_number: str,
    *,
    options: ConsumerInteractionPipelineOptions | None = None,
    fetcher: GmailProconFetcher | None = None,
) -> list[ProcessedConsumerInteraction]:
    """Reprocessa interações enfileiradas quando o item Monday passa a existir."""
    options = options or ConsumerInteractionPipelineOptions()
    processed_message_ids, pending = _load_state(options.state_path)
    matching = [item for item in pending if item.protocol_number == protocol_number]
    if not matching:
        return []

    if fetcher is None:
        if not has_valid_token(options.token_path):
            raise ConsumerInteractionPipelineError("Google não conectado.")
        fetcher = GmailProconFetcher.from_credentials(
            credentials_path=options.credentials_path,
            token_path=options.token_path,
        )

    results: list[ProcessedConsumerInteraction] = []
    for entry in matching:
        notification = fetcher.fetch_notification(entry.message_id)
        if notification is None or notification.notification_type != "interacao_consumidor":
            notification = ProconNotificationEmail(
                message_id=entry.message_id,
                subject=entry.subject,
                sender="procon.naoresponder@procon.sp.gov.br",
                received_at=datetime.fromisoformat(entry.received_at)
                if entry.received_at
                else datetime.now(UTC),
                portal_url="",
                source_id="sp",
                access_code=entry.access_code or "",
                notification_type="interacao_consumidor",
                protocol_number=entry.protocol_number,
                raw_snippet=entry.email_snippet,
            )
        result, processed_message_ids, pending = _process_single_interaction(
            notification,
            options=options,
            processed_message_ids=processed_message_ids,
            pending=pending,
            fetcher=fetcher,
        )
        results.append(result)

    _save_state(
        options.state_path,
        processed_message_ids=processed_message_ids,
        pending=pending,
    )
    return results


def process_consumer_interactions(
    options: ConsumerInteractionPipelineOptions | None = None,
) -> list[ProcessedConsumerInteraction]:
    """Processa e-mails não lidos de interação do consumidor (Procon-SP)."""
    options = options or ConsumerInteractionPipelineOptions()

    if not options.dry_run and not has_valid_token(options.token_path):
        raise ConsumerInteractionPipelineError("Google não conectado. Rode: procon-email auth")

    fetcher = GmailProconFetcher.from_credentials(
        credentials_path=options.credentials_path,
        token_path=options.token_path,
    )

    try:
        notifications = fetcher.list_unread_consumer_interactions(
            max_results=options.max_results,
        )
    except GmailClientError as exc:
        raise ConsumerInteractionPipelineError(str(exc)) from exc

    processed_message_ids, pending = _load_state(options.state_path)
    results: list[ProcessedConsumerInteraction] = []

    for notification in notifications:
        result, processed_message_ids, pending = _process_single_interaction(
            notification,
            options=options,
            processed_message_ids=processed_message_ids,
            pending=pending,
            fetcher=fetcher,
        )
        results.append(result)

    _save_state(
        options.state_path,
        processed_message_ids=processed_message_ids,
        pending=pending,
    )
    return results
