"""Testes de resolução do contrato pai."""

from classificacao_procons.contratos.gemini_extractor import ContractMetadata
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.parent_resolver import (
    ContratosBoardIndex,
    ContratosBoardItem,
    ParentResolutionResult,
    _parse_linked_item_ids,
    resolve_parent_contrato_item,
)


class TestParentResolver:
    def test_should_parse_linked_pulse_ids_from_board_relation(self) -> None:
        raw = '{"linkedPulseIds":[200, 300]}'
        assert _parse_linked_item_ids(raw) == ["200", "300"]

    def test_should_resolve_parent_from_controle_link(self) -> None:
        board_index = ContratosBoardIndex(
            items=(ContratosBoardItem(item_id="200", name="Tower Bridge", cnpj=None),),
            cnpj_column_id=None,
        )
        controle_item = ControleAssinaturasItem(
            item_id="1",
            name="Aditivo",
            status="Assinado",
            tipo=None,
            signature_link=None,
            related_contract_item_ids=("200",),
        )
        metadata = ContractMetadata(
            counterparty_name="Tower Bridge",
            counterparty_cnpj=None,
            contract_type=None,
            company=None,
            start_date=None,
            end_date=None,
            property_name=None,
            summary=None,
        )

        result = resolve_parent_contrato_item(
            api_token="token",
            document_name="Aditivo Locação - Tower Bridge",
            metadata=metadata,
            controle_item=controle_item,
            board_index=board_index,
        )

        assert result == ParentResolutionResult(parent_item_id="200", strategy="controle_link")

    def test_should_resolve_parent_from_cnpj(self) -> None:
        board_index = ContratosBoardIndex(
            items=(
                ContratosBoardItem(
                    item_id="300",
                    name="Amby Natural",
                    cnpj="12345678000190",
                ),
            ),
            cnpj_column_id="cnpj",
        )
        metadata = ContractMetadata(
            counterparty_name="Amby Natural",
            counterparty_cnpj="12.345.678/0001-90",
            contract_type=None,
            company=None,
            start_date=None,
            end_date=None,
            property_name=None,
            summary=None,
        )

        result = resolve_parent_contrato_item(
            api_token="token",
            document_name="Aditivo B2B",
            metadata=metadata,
            board_index=board_index,
        )

        assert result.strategy == "cnpj"
        assert result.parent_item_id == "300"

    def test_should_resolve_parent_from_gemini_reference(self) -> None:
        board_index = ContratosBoardIndex(
            items=(
                ContratosBoardItem(item_id="400", name="Contrato Locação Tower Bridge", cnpj=None),
            ),
            cnpj_column_id=None,
        )
        metadata = ContractMetadata(
            counterparty_name="B4A",
            counterparty_cnpj=None,
            contract_type="Aditivo",
            company="B4A",
            start_date=None,
            end_date=None,
            property_name=None,
            summary=None,
            parent_contract_reference="Contrato Locação Tower Bridge",
            is_supplemental=True,
            supplemental_kind="aditivo",
        )

        result = resolve_parent_contrato_item(
            api_token="token",
            document_name="Aditivo Locação Imóvel",
            metadata=metadata,
            board_index=board_index,
        )

        assert result.parent_item_id == "400"
        assert result.strategy == "gemini_reference"
