"""Testes de atualização Monday para respostas elaboradas."""

import json
from unittest.mock import patch

from classificacao_procons.monday.client import update_elaborated_response_links
from classificacao_procons.monday.mapping import (
    FIELD_RESPONSE_FULL,
    FIELD_RESPONSE_SUMMARY,
    FIELD_RESPONSE_UNIFIED_PDF,
    MondayColumn,
    build_response_column_values,
    resolve_field_for_column,
)


class TestResponseMondayMapping:
    def test_should_map_response_columns(self) -> None:
        assert resolve_field_for_column("Resposta Completa") == FIELD_RESPONSE_FULL
        assert resolve_field_for_column("Resumo Resposta") == FIELD_RESPONSE_SUMMARY
        assert resolve_field_for_column("PDF Unificado") == FIELD_RESPONSE_UNIFIED_PDF

    def test_should_build_response_column_values(self) -> None:
        columns = [
            MondayColumn("col_full", "Resposta Completa", "link"),
            MondayColumn("col_summary", "Resumo Resposta", "link"),
            MondayColumn("col_pdf", "PDF Unificado", "link"),
        ]
        values = build_response_column_values(
            columns,
            full_response_url="https://drive/full",
            summary_response_url="https://drive/summary",
            unified_pdf_url="https://drive/pdf",
        )
        assert values["col_full"]["url"] == "https://drive/full"
        assert values["col_summary"]["url"] == "https://drive/summary"
        assert values["col_pdf"]["url"] == "https://drive/pdf"


@patch("classificacao_procons.monday.client._graphql_request")
@patch("classificacao_procons.monday.client.load_board_metadata")
def test_should_update_monday_item_with_response_links(
    load_board_mock,
    graphql_mock,
) -> None:
    from classificacao_procons.monday.client import MondayBoardContext

    load_board_mock.return_value = MondayBoardContext(
        board_id="board-1",
        group_id="",
        columns=[
            MondayColumn("col_full", "Resposta Completa", "link"),
            MondayColumn("col_summary", "Resumo Resposta", "link"),
        ],
        account_slug="account",
    )

    update_elaborated_response_links(
        item_id="100",
        full_response_url="https://drive/full",
        summary_response_url="https://drive/summary",
        api_token="token",
    )

    graphql_mock.assert_called_once()
    variables = graphql_mock.call_args.kwargs["variables"]
    assert variables["boardId"] == "board-1"
    assert variables["itemId"] == "100"
    payload = json.loads(variables["columnValues"])
    assert payload["col_full"]["url"] == "https://drive/full"
    assert payload["col_summary"]["url"] == "https://drive/summary"
