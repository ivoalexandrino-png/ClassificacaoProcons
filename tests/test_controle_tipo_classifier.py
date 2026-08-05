"""Testes do classificador Tipo (Controle Assinaturas)."""

import pytest

from classificacao_procons.contratos.constants import MONDAY_TIPO_RH
from classificacao_procons.contratos.controle_sync import _resolve_tipo_label
from classificacao_procons.contratos.controle_tipo import (
    classify_controle_tipo_heuristic,
    resolve_controle_tipo_label,
    should_omit_controle_tipo,
)
from classificacao_procons.contratos.gemini_extractor import ContractMetadata


class TestControleTipoHeuristic:
    def test_should_classify_nda_without_minuta_in_title(self) -> None:
        result = classify_controle_tipo_heuristic(document_name="NDA - Fornecedor XYZ")
        assert result.monday_tipo == "NDA"
        assert result.confidence == "high"

    def test_should_classify_four_equity_aditivo_as_societario_follows_principal(self) -> None:
        name = "1º TERMO ADITIVO - 4Equity x BVI-B4A SERVIÇOS x CODEMP 2025"
        result = classify_controle_tipo_heuristic(document_name=name)
        assert result.monday_tipo == "Contratos Societários"
        rationale = result.rationale.casefold()
        assert "acessório" in rationale or "societário" in rationale

    def test_should_classify_aditivo_b2b_follows_principal_title(self) -> None:
        name = "Aditivo ao Contrato de Parceria B2B - Fornecedor ABC"
        result = classify_controle_tipo_heuristic(document_name=name)
        assert result.monday_tipo == "Contratos B2B"
        assert "principal" in result.rationale.casefold()

    def test_should_classify_aditivo_from_metadata_parent_reference(self) -> None:
        metadata = ContractMetadata(
            counterparty_name="HoldCo",
            counterparty_cnpj=None,
            contract_type="aditivo",
            company=None,
            start_date=None,
            end_date=None,
            property_name=None,
            summary=None,
            parent_contract_reference="Acordo 4Equity - Stock Options Colaborador 2026",
            is_supplemental=True,
        )
        result = classify_controle_tipo_heuristic(
            document_name="1º Aditivo - HoldCo",
            metadata=metadata,
        )
        assert result.monday_tipo == "Contratos Societários"

    def test_should_not_classify_four_equity_bvi_as_rv_bvi(self) -> None:
        name = "4Equity x BVI-B4A SERVIÇOS x CODEMP 2025"
        result = classify_controle_tipo_heuristic(document_name=name)
        assert result.monday_tipo != "Contratos RV BVI"

    def test_should_classify_four_equity_token_agreement_as_societario(self) -> None:
        name = "Acordo 4Equity - Stock Options Colaborador 2026"
        result = classify_controle_tipo_heuristic(document_name=name)
        assert result.monday_tipo == "Contratos Societários"

    def test_should_classify_cessao_onerosa_participacao_as_societario(self) -> None:
        name = "Cessão onerosa de participação societária - HoldCo"
        result = classify_controle_tipo_heuristic(document_name=name)
        assert result.monday_tipo == "Contratos Societários"

    def test_should_classify_brass_hill_pedido_as_marcas_proprias(self) -> None:
        name = "Pedido Brass Hill - Glam Nutri wiki- Junho_2026"
        result = classify_controle_tipo_heuristic(document_name=name)
        assert result.monday_tipo == "Pedidos Marcas Próprias"

    def test_should_classify_minuta_parceria_as_b2b(self) -> None:
        assert (
            _resolve_tipo_label(
                document_name="4.1 - Minuta Contrato Parceria - B4A - GE Beauty",
            )
            == "Contratos B2B"
        )

    def test_should_return_none_for_procuracao(self) -> None:
        assert (
            resolve_controle_tipo_label(
                document_name="Procuração - Jan __ Carol - localiza 16.07.2026",
                min_confidence="low",
            )
            is None
        )

    def test_should_classify_pj_aditivo_as_rh_not_omit(self) -> None:
        name = "Aditivo Contrato PJ Interno - Maria Souza 2026"
        assert should_omit_controle_tipo(document_name=name) is False
        result = classify_controle_tipo_heuristic(document_name=name)
        assert result.monday_tipo == MONDAY_TIPO_RH

    def test_should_use_metadata_company_for_entity(self) -> None:
        metadata = ContractMetadata(
            counterparty_name="Fornecedor X",
            counterparty_cnpj=None,
            contract_type="Prestação de serviços",
            company="MMKT",
            start_date=None,
            end_date=None,
            property_name=None,
            summary=None,
        )
        result = classify_controle_tipo_heuristic(
            document_name="Contrato de prestação de serviços - Fornecedor X",
            metadata=metadata,
        )
        assert result.monday_tipo == "Contratos MMKT"

    @pytest.mark.parametrize(
        "document_name",
        [
            "Termo de Rescisão - Karen Santos",
            "Código de Conduta - Beatriz Tayna",
            "TCE - Ana Costa 2026",
        ],
    )
    def test_should_classify_rh_family(self, document_name: str) -> None:
        result = classify_controle_tipo_heuristic(document_name=document_name)
        assert result.monday_tipo == MONDAY_TIPO_RH
