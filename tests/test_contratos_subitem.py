"""Testes de subitem e busca de contrato pai no Monday."""

from unittest.mock import patch

from classificacao_procons.contratos.gemini_extractor import ContractMetadata
from classificacao_procons.contratos.monday_contracts import (
    find_parent_contrato_item,
    register_contrato_subitem,
)


class TestContratosSubitem:
    @patch("classificacao_procons.contratos.monday_contracts._graphql_request")
    def test_should_find_parent_contrato_item_by_name_match(self, graphql_mock) -> None:
        graphql_mock.return_value = {
            "boards": [
                {
                    "items_page": {
                        "cursor": None,
                        "items": [
                            {"id": "100", "name": "Amby Natural"},
                            {"id": "200", "name": "Tower Bridge"},
                        ],
                    }
                }
            ]
        }
        metadata = ContractMetadata(
            counterparty_name="Tower Bridge Empreendimentos",
            counterparty_cnpj=None,
            contract_type=None,
            company=None,
            start_date=None,
            end_date=None,
            property_name="Tower Bridge",
            summary=None,
        )

        parent_id = find_parent_contrato_item(
            api_token="token",
            document_name="Aditivo Locação Imóvel - Tower Bridge",
            metadata=metadata,
        )

        assert parent_id == "200"

    @patch("classificacao_procons.contratos.monday_contracts._apply_contratos_column_values")
    @patch("classificacao_procons.contratos.monday_contracts._load_contratos_column_details")
    @patch("classificacao_procons.contratos.monday_contracts.load_board_metadata")
    @patch("classificacao_procons.contratos.monday_contracts._graphql_request")
    def test_should_register_contrato_subitem(
        self,
        graphql_mock,
        load_board_mock,
        load_columns_mock,
        apply_columns_mock,
    ) -> None:
        from classificacao_procons.monday.client import MondayBoardContext
        from classificacao_procons.monday.mapping import MondayColumn

        graphql_mock.return_value = {"create_subitem": {"id": "999"}}
        load_board_mock.return_value = MondayBoardContext(
            board_id="5385471914",
            account_slug="b4a",
            columns=[],
            group_id="topics",
        )
        load_columns_mock.return_value = [
            type(
                "Detail",
                (),
                {
                    "column": MondayColumn(id="cnpj", title="CNPJ", column_type="text"),
                    "settings_str": None,
                },
            )()
        ]
        metadata = ContractMetadata(
            counterparty_name="Tower Bridge",
            counterparty_cnpj="12.345.678/0001-90",
            contract_type="Aditivo",
            company=None,
            start_date=None,
            end_date=None,
            property_name=None,
            summary=None,
        )

        result = register_contrato_subitem(
            api_token="token",
            parent_item_id="200",
            metadata=metadata,
            document_name="Aditivo Locação - Tower Bridge",
            signed_pdf_url="https://drive/file.pdf",
        )

        assert result.contratos_item_id == "999"
        assert result.parent_item_id == "200"
        assert result.registration_mode == "subitem"
        create_call = graphql_mock.call_args
        assert create_call.kwargs["variables"]["parentItemId"] == "200"
