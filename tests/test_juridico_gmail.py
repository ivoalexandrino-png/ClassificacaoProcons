"""Testes do cliente Gmail de intimações."""

import base64
from unittest.mock import MagicMock

from classificacao_procons.juridico.gmail import GmailIntimacaoFetcher


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _message(body: str, *, subject: str = "Intimação eletrônica") -> dict:
    return {
        "snippet": "trecho",
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": "Tribunal <push@tjsp.jus.br>"},
                {"name": "Date", "value": "Fri, 17 Jul 2026 09:00:00 -0300"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _encode(body)},
        },
    }


def _service_for(message: dict) -> MagicMock:
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    messages.get.return_value.execute.return_value = message
    return service


class TestFetchIntimacao:
    def test_should_parse_intimacao_message(self) -> None:
        body = (
            "Processo nº 1023456-78.2026.8.26.0100 - TJSP. "
            "Intimação para contestar no prazo de 15 dias úteis."
        )
        fetcher = GmailIntimacaoFetcher(_service_for(_message(body)))
        intimacao = fetcher.fetch_intimacao("id-1")
        assert intimacao is not None
        assert intimacao.process_number == "1023456-78.2026.8.26.0100"
        assert intimacao.tribunal == "TJSP"
        assert intimacao.prazo_dias == 15

    def test_should_return_none_for_non_intimacao(self) -> None:
        message = _message("Promoção imperdível, compre já!", subject="Oferta")
        fetcher = GmailIntimacaoFetcher(_service_for(message))
        assert fetcher.fetch_intimacao("id-2") is None

    def test_should_return_none_when_no_process_number(self) -> None:
        message = _message("Intimação sem número de processo identificável.")
        fetcher = GmailIntimacaoFetcher(_service_for(message))
        assert fetcher.fetch_intimacao("id-3") is None


class TestListUnread:
    def test_should_list_and_filter(self) -> None:
        body = "Processo 1023456-78.2026.8.26.0100 intimação para manifestar em 5 dias."
        service = MagicMock()
        messages = service.users.return_value.messages.return_value
        messages.list.return_value.execute.return_value = {"messages": [{"id": "id-1"}]}
        messages.get.return_value.execute.return_value = _message(body)

        fetcher = GmailIntimacaoFetcher(service)
        result = fetcher.list_unread_intimacoes()
        assert len(result) == 1
        assert result[0].process_number == "1023456-78.2026.8.26.0100"
