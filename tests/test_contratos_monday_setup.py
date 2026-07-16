"""Testes de setup Monday para contratos."""

from unittest.mock import patch

from classificacao_procons.contratos.monday_setup import (
    CONTROLE_COL_CONTRATO_RELACIONADO_TITLE,
    ensure_controle_contrato_relacionado_column,
)


class TestMondaySetup:
    @patch("classificacao_procons.contratos.monday_setup._graphql_request_with_version")
    def test_should_return_existing_related_contract_column(self, graphql_mock) -> None:
        graphql_mock.return_value = {
            "boards": [
                {
                    "columns": [
                        {
                            "id": "link_col",
                            "title": CONTROLE_COL_CONTRATO_RELACIONADO_TITLE,
                            "type": "board_relation",
                        }
                    ]
                }
            ]
        }

        result = ensure_controle_contrato_relacionado_column(api_token="token")

        assert result.column_id == "link_col"
        assert result.created is False
        assert graphql_mock.call_count == 1

    @patch("classificacao_procons.contratos.monday_setup._graphql_request_with_version")
    def test_should_create_related_contract_column_when_missing(self, graphql_mock) -> None:
        graphql_mock.side_effect = [
            {"boards": [{"columns": []}]},
            {"create_column": {"id": "new_link_col", "title": "Contrato relacionado"}},
        ]

        result = ensure_controle_contrato_relacionado_column(api_token="token")

        assert result.column_id == "new_link_col"
        assert result.created is True
        create_call = graphql_mock.call_args_list[1]
        assert create_call.kwargs["variables"]["title"] == CONTROLE_COL_CONTRATO_RELACIONADO_TITLE
        assert create_call.kwargs["variables"]["defaults"]["boardIds"] == [5385471914]
