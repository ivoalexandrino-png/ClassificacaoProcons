"""Cliente Gmail para buscar notificações do Procon-SP."""

from __future__ import annotations

import base64
import os
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from classificacao_procons.email.parser import (
    is_procon_cip_notification,
    parse_procon_notification_body,
    ProconEmailParseError,
)
from classificacao_procons.models import ProconNotificationEmail

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
DEFAULT_GMAIL_QUERY = (
    'from:procon.naoresponder@procon.sp.gov.br '
    'subject:"Fundação Procon-SP - Notificação de emissão de CIP"'
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
    """Busca e-mails de notificação CIP do Procon-SP via Gmail API."""

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
        scopes = scopes or [GMAIL_READONLY_SCOPE]
        credentials = _load_credentials(credentials_path, token_path, scopes)
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        return cls(service)

    def list_unread_notifications(
        self,
        *,
        max_results: int = 20,
        query: str | None = None,
    ) -> list[ProconNotificationEmail]:
        """Lista notificações não lidas que correspondem ao filtro Procon-SP."""
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
        """Busca e parseia um e-mail pelo ID. Retorna None se não for notificação Procon."""
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

        if not is_procon_cip_notification(subject=subject, sender=sender):
            return None

        text_plain, text_html = _extract_bodies(payload)
        try:
            parsed = parse_procon_notification_body(html=text_html, text=text_plain)
        except ProconEmailParseError:
            return None

        return ProconNotificationEmail(
            message_id=message_id,
            subject=subject,
            sender=sender,
            received_at=_parse_received_at(headers),
            portal_url=parsed.portal_url,
            access_code=parsed.access_code,
            protocol_number=parsed.protocol_number,
            email_response_deadline=parsed.response_deadline,
            raw_snippet=message.get("snippet"),
        )

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


def _load_credentials(
    credentials_path: str,
    token_path: str,
    scopes: list[str],
) -> Credentials:
    credentials: Credentials | None = None
    if os.path.exists(token_path):
        credentials = Credentials.from_authorized_user_file(token_path, scopes)

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if credentials and credentials.valid:
        return credentials

    if not os.path.exists(credentials_path):
        raise GmailClientError(
            f"Arquivo de credenciais OAuth não encontrado: {credentials_path}. "
            "Configure as credenciais do Gmail conforme o README."
        )

    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes)
    credentials = flow.run_local_server(port=0)

    with open(token_path, "w", encoding="utf-8") as token_file:
        token_file.write(credentials.to_json())

    return credentials
