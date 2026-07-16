"""Testes de roteamento Controle → Contratos."""

from datetime import date

from classificacao_procons.contratos.contratos_routing import (
    extract_parent_search_terms,
    is_supplemental_document,
    resolve_contratos_registration_mode,
    score_parent_name_match,
)
from classificacao_procons.contratos.gemini_extractor import ContractMetadata


class TestContratosRouting:
    def test_should_detect_supplemental_document_from_name(self) -> None:
        assert is_supplemental_document(document_name="Aditivo Locação Imóvel - Tower Bridge")
        assert is_supplemental_document(document_name="Distrato B2B - Amby Natural")
        assert not is_supplemental_document(document_name="Contrato B2B - Amby Natural")

    def test_should_use_monday_automation_when_tipo_is_filled(self) -> None:
        mode = resolve_contratos_registration_mode(
            controle_tipo="Contratos B2B",
            controle_item_found=True,
        )
        assert mode == "monday_automation"

    def test_should_create_subitem_when_tipo_is_empty(self) -> None:
        mode = resolve_contratos_registration_mode(
            controle_tipo=None,
            controle_item_found=True,
        )
        assert mode == "subitem"

    def test_should_skip_contratos_when_controle_item_missing(self) -> None:
        mode = resolve_contratos_registration_mode(
            controle_tipo="Contratos B2B",
            controle_item_found=False,
        )
        assert mode == "skip"

    def test_should_extract_parent_search_terms_from_aditivo_name(self) -> None:
        metadata = ContractMetadata(
            counterparty_name="Tower Bridge Empreendimentos",
            counterparty_cnpj=None,
            contract_type="Aditivo",
            company="B4A",
            start_date=date(2026, 1, 1),
            end_date=None,
            property_name="Tower Bridge",
            summary=None,
        )

        terms = extract_parent_search_terms(
            document_name="Aditivo Locação Imóvel - Tower Bridge",
            metadata=metadata,
        )

        assert "Tower Bridge Empreendimentos" in terms
        assert "Tower Bridge" in terms

    def test_should_score_exact_parent_name_higher_than_partial(self) -> None:
        exact = score_parent_name_match(
            item_name="Tower Bridge",
            search_term="Tower Bridge",
        )
        partial = score_parent_name_match(
            item_name="Contrato Locação Tower Bridge",
            search_term="Tower Bridge Empreendimentos",
        )

        assert exact > partial
