"""Cliente Gmail para buscar notificações Procon/Proconsumidor."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from classificacao_procons.campinas.email_parser import (
    CAMPINAS_PORTAL_URL,
    CAMPINAS_STATE_LABEL,
    CampinasEmailParseError,
    is_campinas_notification,
    parse_campinas_notification_body,
)
from classificacao_procons.email.parser import (
    ProconEmailParseError,
    _html_to_text,
    is_procon_cip_notification,
    parse_procon_notification_body,
)
from classificacao_procons.google_auth import load_credentials
from classificacao_procons.models import ProconNotificationEmail
from classificacao_procons.proconsumidor.email_parser import (
    PROCONSUMIDOR_PORTAL_URL,
    ProconsumidorEmailParseError,
    is_proconsumidor_notification,
    parse_proconsumidor_notification_body,
)
from classificacao_procons.sc.email_parser import (
    SC_STATE_LABEL,
    ScEmailParseError,
    is_sc_ssp_notification,
    parse_sc_ssp_notification,
)

DEFAULT_GMAIL_QUERY = (
    '('
    'from:procon.naoresponder@procon.sp.gov.br '
    'subject:"Fundação Procon-SP - Notificação de emissão de CIP"'
    ') OR ('
    'from:admin@proconsumidor.mj.gov.br '
    'subject:"Proconsumidor - Notificação"'
    ') OR ('
    'from:procon.adm@campinas.sp.gov.br'
    ') OR ('
    'subject:"Processo SSP"'
    ')'
)


class GmailClientError(RuntimeError):
    """Erro ao comunicar com a API do Gmail."""


def _decode_body_data(data: str) -> str:
    raw = base64.urlsafe_b64decode(data.encode("utf-8"))
    return raw.decode("utf-8", errors="replace")


def _extract_bodies(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """Retorna (text_plain, text_html) do payload MIME."""
    text_plain: str | None = None
    text_html: str | None = None

    def walk(part: dict[str, Any]) -> None:
        nonlocal text_plain, text_html
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if data:
            decoded = _decode_body_data(data)
            if mime_type == "text/plain" and text_plain is None:
                text_plain = decoded
            elif mime_type == "text/html" and text_html is None:
                text_html = decoded
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    return text_plain, text_html


def _header_value(headers: list[dict[str, str]], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _parse_received_at(headers: list[dict[str, str]]) -> datetime:
    date_header = _header_value(headers, "Date")
    if not date_header:
        return datetime.now(UTC)
    try:
        parsed = parsedate_to_datetime(date_header)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


class GmailProconFetcher:
    """Busca e-mails de notificação Procon/Proconsumidor via Gmail API."""

    def __init__(self, service: Any) -> None:
        self._service = service

    @classmethod
    def from_credentials(
        cls,
        *,
        credentials_path: str,
        token_path: str,
        scopes: list[str] | None = None,
    ) -> GmailProconFetcher:
        del credentials_path, scopes
        credentials = load_credentials(token_path)
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        return cls(service)

    def list_unread_notifications(
        self,
        *,
        max_results: int = 20,
        query: str | None = None,
    ) -> list[ProconNotificationEmail]:
        """Lista notificações não lidas que correspondem ao filtro Procon/Proconsumidor."""
        gmail_query = query or f"{DEFAULT_GMAIL_QUERY} is:unread"
        try:
            list_response = (
                self._service.users()
                .messages()
                .list(userId="me", q=gmail_query, maxResults=max_results)
                .execute()
            )
        except HttpError as exc:
            raise GmailClientError(f"Falha ao listar mensagens: {exc}") from exc

        messages = list_response.get("messages", [])
        notifications: list[ProconNotificationEmail] = []
        for message_ref in messages:
            notification = self.fetch_notification(message_ref["id"])
            if notification is not None:
                notifications.append(notification)
        return notifications

    def fetch_notification(self, message_id: str) -> ProconNotificationEmail | None:
        """Busca e parseia um e-mail pelo ID. Retorna None se não for notificação suportada."""
        try:
            message = (
                self._service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
        except HttpError as exc:
            raise GmailClientError(f"Falha ao buscar mensagem {message_id}: {exc}") from exc

        payload = message.get("payload", {})
        headers = payload.get("headers", [])
        subject = _header_value(headers, "Subject")
        sender = _header_value(headers, "From")

        text_plain, text_html = _extract_bodies(payload)
        body_text = text_plain or ""
        if text_html:
            body_text = f"{body_text}\n{_html_to_text(text_html)}".strip()
        received_at = _parse_received_at(headers)
        snippet = message.get("snippet")

        if is_sc_ssp_notification(subject=subject, sender=sender, body=body_text):
            try:
                parsed = parse_sc_ssp_notification(
                    subject=subject,
                    html=text_html,
                    text=text_plain,
                )
            except ScEmailParseError:
                return None
            return ProconNotificationEmail(
                message_id=message_id,
                subject=subject,
                sender=sender,
                received_at=received_at,
                portal_url="",
                source_id="sc",
                protocol_number=parsed.protocol_number,
                state=SC_STATE_LABEL,
                raw_snippet=snippet,
            )

        if is_proconsumidor_notification(subject=subject, sender=sender):
            try:
                parsed = parse_proconsumidor_notification_body(html=text_html, text=text_plain)
            except ProconsumidorEmailParseError:
                return None
            return ProconNotificationEmail(
                message_id=message_id,
                subject=subject,
                sender=sender,
                received_at=received_at,
                portal_url=PROCONSUMIDOR_PORTAL_URL,
                source_id="proconsumidor",
                protocol_number=parsed.complaint_number,
                regional_org=parsed.regional_org,
                state=parsed.state,
                raw_snippet=snippet,
            )

        if is_campinas_notification(subject=subject, sender=sender):
            try:
                parsed = parse_campinas_notification_body(html=text_html, text=text_plain)
            except CampinasEmailParseError:
                return None
            return ProconNotificationEmail(
                message_id=message_id,
                subject=subject,
                sender=sender,
                received_at=received_at,
                portal_url=CAMPINAS_PORTAL_URL,
                source_id="campinas",
                protocol_number=parsed.protocol_number,
                state=CAMPINAS_STATE_LABEL,
                consumer_name=parsed.consumer_name,
                consumer_cpf=parsed.consumer_cpf,
                complaint_date=parsed.complaint_date,
                raw_snippet=snippet,
            )

        if not is_procon_cip_notification(subject=subject, sender=sender):
            return None

        try:
            parsed = parse_procon_notification_body(html=text_html, text=text_plain)
        except ProconEmailParseError:
            return None

        return ProconNotificationEmail(
            message_id=message_id,
            subject=subject,
            sender=sender,
            received_at=received_at,
            portal_url=parsed.portal_url,
            source_id="sp",
            access_code=parsed.access_code,
            protocol_number=parsed.protocol_number,
            email_response_deadline=parsed.response_deadline,
            raw_snippet=snippet,
        )

    def fetch_message_payload(self, message_id: str) -> dict[str, Any]:
        """Retorna o payload MIME completo de uma mensagem."""
        try:
            message = (
                self._service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
        except HttpError as exc:
            raise GmailClientError(f"Falha ao buscar mensagem {message_id}: {exc}") from exc
        return message.get("payload", {})

    def mark_as_read(self, message_id: str) -> None:
        """Remove o label UNREAD da mensagem após processamento."""
        try:
            (
                self._service.users()
                .messages()
                .modify(userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]})
                .execute()
            )
        except HttpError as exc:
            raise GmailClientError(
                f"Falha ao marcar mensagem {message_id} como lida: {exc}",
            ) from exc

