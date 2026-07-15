"""Testes do cliente Monday.com."""

from datetime import date
from unittest.mock import patch

import pytest

from classificacao_procons.models import ProcessedComplaint
from classificacao_procons.monday.client import MondayClientError, register_complaint


def _processed_complaint() -> ProcessedComplaint:
    return ProcessedComplaint(
        status="success",
        message_id="msg-1",
        access_code="CODE-123",
        protocol_number="1653213/2026",
        consumer_name="MARIA SILVA",
        consumer_cpf="12345678901",
        complaint_date=date(2026, 7, 14),
        procon_response_deadline=date(2026, 7, 24),
        sac_deadline=date(2026, 7, 19),
        legal_deadline=date(2026, 7, 20),
        cause="Atraso na entrega",
        state="SP",
        pdf_url="https://drive.google.com/file/abc/view",
        drive_folder_url="https://drive.google.com/folder/abc",
    )


BOARD_RESPONSE = {
    "me": {"account": {"slug": "b4a"}},
    "boards": [
        {
            "id": "111",
            "name": "procons",
            "groups": [{"id": "grp_pending", "title": "pendentes de resposta"}],
            "columns": [
                {"id": "text_protocol", "title": "CIP/FA", "type": "text"},
                {"id": "text_cpf", "title": "CPF", "type": "text"},
                {"id": "link_pdf", "title": "PDF Drive", "type": "link"},
            ],
        },
    ],
}

CREATE_ITEM_RESPONSE = {"create_item": {"id": "999"}}


class TestMondayClient:
    def test_should_return_none_when_token_missing(self) -> None:
        result = register_complaint(_processed_complaint(), api_token=None)
        assert result is None

    @patch("classificacao_procons.monday.client._graphql_request")
    def test_should_create_item_on_monday(self, graphql_mock) -> None:
        graphql_mock.side_effect = [
            BOARD_RESPONSE,
            {"items_page_by_column_values": {"items": []}},
            CREATE_ITEM_RESPONSE,
        ]

        result = register_complaint(_processed_complaint(), api_token="token-test")

        assert result is not None
        assert result.item_id == "999"
        assert result.item_url == "https://b4a.monday.com/boards/111/pulses/999"
        assert graphql_mock.call_count == 3

    @patch("classificacao_procons.monday.client._graphql_request")
    def test_should_skip_duplicate_protocol(self, graphql_mock) -> None:
        graphql_mock.side_effect = [
            BOARD_RESPONSE,
            {"items_page_by_column_values": {"items": [{"id": "888"}]}},
        ]

        result = register_complaint(_processed_complaint(), api_token="token-test")

        assert result is not None
        assert result.skipped_duplicate is True
        assert result.item_id == "888"
        assert graphql_mock.call_count == 2

    def test_should_raise_when_complaint_not_successful(self) -> None:
        complaint = ProcessedComplaint(
            status="error",
            message_id="msg-1",
            access_code="CODE-123",
            protocol_number="1653213/2026",
            consumer_name="",
            consumer_cpf="",
            complaint_date=None,
            procon_response_deadline=None,
            sac_deadline=None,
            legal_deadline=None,
            cause="",
            state="SP",
            pdf_url=None,
            drive_folder_url=None,
            error="falha",
        )

        with pytest.raises(MondayClientError, match="processadas com sucesso"):
            register_complaint(complaint, api_token="token-test")
