"""Testes do cliente Gmail (com mocks)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from classificacao_procons.email.gmail import GmailProconFetcher
from classificacao_procons.models import ProconNotificationEmail


def _build_gmail_message() -> dict:
  import base64

  html = (
      "<html><body>"
      "<p>Código de acesso: ABC123-XYZ789</p>"
      '<a href="https://fornecedor2.procon.sp.gov.br/login">Portal</a>'
      "</body></html>"
  )
  encoded = base64.urlsafe_b64encode(html.encode()).decode()

  return {
      "id": "msg-001",
      "snippet": "Notificação de emissão de CIP",
      "payload": {
          "headers": [
              {"name": "Subject", "value": "Fundação Procon-SP - Notificação de emissão de CIP"},
              {"name": "From", "value": "procon.naoresponder@procon.sp.gov.br"},
              {"name": "Date", "value": "Mon, 14 Jul 2025 10:00:00 +0000"},
          ],
          "mimeType": "text/html",
          "body": {"data": encoded},
      },
  }


class TestGmailProconFetcher:
    def test_should_fetch_and_parse_procon_notification(self) -> None:
        service = MagicMock()
        users = service.users.return_value
        messages = users.messages.return_value
        messages.get.return_value.execute.return_value = _build_gmail_message()

        fetcher = GmailProconFetcher(service)
        result = fetcher.fetch_notification("msg-001")

        assert result == ProconNotificationEmail(
            message_id="msg-001",
            subject="Fundação Procon-SP - Notificação de emissão de CIP",
            sender="procon.naoresponder@procon.sp.gov.br",
            received_at=datetime(2025, 7, 14, 10, 0, tzinfo=UTC),
            portal_url="https://fornecedor2.procon.sp.gov.br/login",
            source_id="sp",
            access_code="ABC123-XYZ789",
            raw_snippet="Notificação de emissão de CIP",
        )

    def test_should_return_none_when_email_is_not_procon_notification(self) -> None:
        message = _build_gmail_message()
        message["payload"]["headers"][0]["value"] = "Assunto diferente"
        service = MagicMock()
        service.users.return_value.messages.return_value.get.return_value.execute.return_value = (
            message
        )

        fetcher = GmailProconFetcher(service)
        assert fetcher.fetch_notification("msg-002") is None

    def test_should_list_unread_notifications(self) -> None:
        service = MagicMock()
        users = service.users.return_value
        messages = users.messages.return_value
        messages.list.return_value.execute.return_value = {
            "messages": [{"id": "msg-001"}, {"id": "msg-002"}],
        }
        messages.get.return_value.execute.side_effect = [
            _build_gmail_message(),
            _build_gmail_message(),
        ]

        fetcher = GmailProconFetcher(service)
        results = fetcher.list_unread_notifications(max_results=2)

        assert len(results) == 2
        assert results[0].access_code == "ABC123-XYZ789"
        messages.list.assert_called_once()
        list_kwargs = messages.list.call_args.kwargs
        assert "is:unread" in list_kwargs["q"]

    def test_should_mark_message_as_read(self) -> None:
        service = MagicMock()
        fetcher = GmailProconFetcher(service)
        fetcher.mark_as_read("msg-001")

        modify = service.users.return_value.messages.return_value.modify
        modify.assert_called_once_with(
            userId="me",
            id="msg-001",
            body={"removeLabelIds": ["UNREAD"]},
        )

    def test_should_fetch_and_parse_campinas_notification(self) -> None:
        import base64

        html = (
            "<html><body>"
            "<p>CIP nº 12345/2026/CIP</p>"
            "<p>Nome: JOAO SANTOS</p>"
            "<p>CPF: 987.654.321-00</p>"
            "<p>Data: 01/07/2026</p>"
            "</body></html>"
        )
        encoded = base64.urlsafe_b64encode(html.encode()).decode()
        message = {
            "id": "msg-campinas",
            "snippet": "Notificação CIP",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Notificação CIP"},
                    {"name": "From", "value": "procon.adm@campinas.sp.gov.br"},
                    {"name": "Date", "value": "Thu, 10 Jul 2026 12:00:00 +0000"},
                ],
                "mimeType": "text/html",
                "body": {"data": encoded},
            },
        }
        service = MagicMock()
        service.users.return_value.messages.return_value.get.return_value.execute.return_value = (
            message
        )

        fetcher = GmailProconFetcher(service)
        result = fetcher.fetch_notification("msg-campinas")

        assert result is not None
        assert result.source_id == "campinas"
        assert result.protocol_number == "12345/2026"
        assert result.consumer_name == "JOAO SANTOS"
        assert result.state == "Campinas"
