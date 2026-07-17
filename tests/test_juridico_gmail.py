"""Testes do cliente Gmail jurídico (com mocks)."""

import base64
from unittest.mock import MagicMock

from classificacao_procons.juridico.gmail import GmailJuridicoFetcher


def _build_gmail_message(
    *,
    subject: str = "Intimação eletrônica",
    sender: str = "naoresponda@tjsp.jus.br",
    body: str = "Processo 1001234-56.2026.8.26.0100. Prazo de 15 dias úteis.",
) -> dict:
    encoded = base64.urlsafe_b64encode(body.encode()).decode()
    return {
        "id": "msg-001",
        "snippet": "Intimação",
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "Date", "value": "Fri, 17 Jul 2026 10:00:00 +0000"},
            ],
            "mimeType": "text/plain",
            "body": {"data": encoded},
        },
    }


class TestGmailJuridicoFetcher:
    def test_should_fetch_judicial_notification(self) -> None:
        service = MagicMock()
        messages = service.users.return_value.messages.return_value
        messages.get.return_value.execute.return_value = _build_gmail_message()

        fetcher = GmailJuridicoFetcher(service)
        result = fetcher.fetch_notification("msg-001")

        assert result is not None
        assert result.message_id == "msg-001"
        assert result.subject == "Intimação eletrônica"
        assert "1001234-56.2026.8.26.0100" in result.body_text

    def test_should_return_none_when_email_is_not_judicial(self) -> None:
        service = MagicMock()
        messages = service.users.return_value.messages.return_value
        messages.get.return_value.execute.return_value = _build_gmail_message(
            subject="Newsletter semanal",
            sender="news@empresa.com.br",
        )

        fetcher = GmailJuridicoFetcher(service)
        assert fetcher.fetch_notification("msg-002") is None

    def test_should_return_none_when_body_is_empty(self) -> None:
        message = _build_gmail_message()
        message["payload"]["body"] = {}
        service = MagicMock()
        messages = service.users.return_value.messages.return_value
        messages.get.return_value.execute.return_value = message

        fetcher = GmailJuridicoFetcher(service)
        assert fetcher.fetch_notification("msg-003") is None

    def test_should_list_unread_notifications_with_query(self) -> None:
        service = MagicMock()
        messages = service.users.return_value.messages.return_value
        messages.list.return_value.execute.return_value = {"messages": [{"id": "msg-001"}]}
        messages.get.return_value.execute.return_value = _build_gmail_message()

        fetcher = GmailJuridicoFetcher(service)
        results = fetcher.list_unread_notifications(max_results=5)

        assert len(results) == 1
        list_kwargs = messages.list.call_args.kwargs
        assert "is:unread" in list_kwargs["q"]
        assert list_kwargs["maxResults"] == 5

    def test_should_mark_message_as_read(self) -> None:
        service = MagicMock()
        fetcher = GmailJuridicoFetcher(service)
        fetcher.mark_as_read("msg-001")

        modify = service.users.return_value.messages.return_value.modify
        modify.assert_called_once_with(
            userId="me",
            id="msg-001",
            body={"removeLabelIds": ["UNREAD"]},
        )
