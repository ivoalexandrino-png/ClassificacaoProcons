"""Cliente Gmail para buscar intimações judiciais e pushes processuais."""

from __future__ import annotations

import os
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from classificacao_procons.email.gmail import (
    GmailClientError,
    _extract_bodies,
    _header_value,
    _parse_received_at,
)
from classificacao_procons.email.parser import _html_to_text
from classificacao_procons.google_auth import load_credentials
from classificacao_procons.juridico.models import JudicialNotificationEmail
from classificacao_procons.juridico.parser import is_judicial_notification

ENV_GMAIL_QUERY = "JURIDICO_GMAIL_QUERY"
DEFAULT_GMAIL_QUERY = (
    '(from:jus.br OR subject:(intimação OR citação OR audiência OR "movimentação processual"))'
)


def get_gmail_query_from_env() -> str:
    query = os.environ.get(ENV_GMAIL_QUERY, "").strip()
    return query or DEFAULT_GMAIL_QUERY


class GmailJuridicoFetcher:
    """Busca e-mails de intimação/push judicial via Gmail API."""

    def __init__(self, service: Any) -> None:
        self._service = service

    @classmethod
    def from_credentials(
        cls,
        *,
        credentials_path: str,
        token_path: str,
    ) -> GmailJuridicoFetcher:
        del credentials_path
        credentials = load_credentials(token_path)
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        return cls(service)

    def list_unread_notifications(
        self,
        *,
        max_results: int = 20,
        query: str | None = None,
    ) -> list[JudicialNotificationEmail]:
        """Lista intimações não lidas que correspondem ao filtro judicial."""
        gmail_query = f"{query or get_gmail_query_from_env()} is:unread"
        try:
            list_response = (
                self._service.users()
                .messages()
                .list(userId="me", q=gmail_query, maxResults=max_results)
                .execute()
            )
        except HttpError as exc:
            raise GmailClientError(f"Falha ao listar mensagens: {exc}") from exc

        notifications: list[JudicialNotificationEmail] = []
        for message_ref in list_response.get("messages", []):
            notification = self.fetch_notification(message_ref["id"])
            if notification is not None:
                notifications.append(notification)
        return notifications

    def fetch_notification(self, message_id: str) -> JudicialNotificationEmail | None:
        """Busca um e-mail pelo ID. Retorna None se não for intimação judicial."""
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

        if not is_judicial_notification(subject=subject, sender=sender):
            return None

        text_plain, text_html = _extract_bodies(payload)
        body_text = text_plain or ""
        if text_html:
            body_text = f"{body_text}\n{_html_to_text(text_html)}".strip()
        if not body_text:
            return None

        return JudicialNotificationEmail(
            message_id=message_id,
            subject=subject,
            sender=sender,
            received_at=_parse_received_at(headers),
            body_text=body_text,
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
