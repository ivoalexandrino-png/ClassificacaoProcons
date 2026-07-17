"""Cliente Gmail para buscar intimações/pushes processuais."""

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
from classificacao_procons.google_auth import load_credentials
from classificacao_procons.juridico.models import IntimacaoEmail
from classificacao_procons.juridico.parser import (
    IntimacaoParseError,
    derive_tribunal_from_cnj,
    looks_like_intimacao,
    parse_intimacao_body,
)

ENV_GMAIL_QUERY = "JURIDICO_GMAIL_QUERY"
DEFAULT_GMAIL_QUERY = (
    '(intimação OR intimacao OR "andamento processual" OR "processo nº" '
    'OR "autos nº" OR publicação OR audiência)'
)

__all__ = [
    "DEFAULT_GMAIL_QUERY",
    "GmailClientError",
    "GmailIntimacaoFetcher",
]


def get_gmail_query_from_env() -> str:
    query = os.environ.get(ENV_GMAIL_QUERY, "").strip()
    return query or DEFAULT_GMAIL_QUERY


class GmailIntimacaoFetcher:
    """Busca e-mails de intimação/andamento processual via Gmail API."""

    def __init__(self, service: Any) -> None:
        self._service = service

    @classmethod
    def from_credentials(
        cls,
        *,
        credentials_path: str,
        token_path: str,
        scopes: list[str] | None = None,
    ) -> GmailIntimacaoFetcher:
        del credentials_path, scopes
        credentials = load_credentials(token_path)
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        return cls(service)

    def list_unread_intimacoes(
        self,
        *,
        max_results: int = 20,
        query: str | None = None,
    ) -> list[IntimacaoEmail]:
        """Lista intimações não lidas que correspondem ao filtro configurado."""
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

        messages = list_response.get("messages", [])
        intimacoes: list[IntimacaoEmail] = []
        for message_ref in messages:
            intimacao = self.fetch_intimacao(message_ref["id"])
            if intimacao is not None:
                intimacoes.append(intimacao)
        return intimacoes

    def fetch_intimacao(self, message_id: str) -> IntimacaoEmail | None:
        """Busca e parseia um e-mail. Retorna None se não for uma intimação."""
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
        body_for_check = text_plain or ""
        if text_html:
            body_for_check = f"{body_for_check}\n{text_html}"

        if not looks_like_intimacao(subject=subject, body=body_for_check):
            return None

        try:
            parsed = parse_intimacao_body(html=text_html, text=text_plain)
        except IntimacaoParseError:
            return None

        tribunal = parsed.tribunal or derive_tribunal_from_cnj(parsed.process_number)
        return IntimacaoEmail(
            message_id=message_id,
            subject=subject,
            sender=sender,
            received_at=_parse_received_at(headers),
            process_number=parsed.process_number,
            tribunal=tribunal,
            vara=parsed.vara,
            movement_type=parsed.movement_type,
            prazo_dias=parsed.prazo_dias,
            prazo_uteis=parsed.prazo_uteis,
            publication_date=parsed.publication_date,
            hearing_at=parsed.hearing_at,
            portal_url=parsed.portal_url,
            body_excerpt=parsed.body_excerpt,
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
