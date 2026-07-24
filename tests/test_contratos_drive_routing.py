"""Testes de roteamento de pastas do Drive para contratos."""

import pytest

from classificacao_procons.contratos.constants import (
    DRIVE_FOLDER_CONTRATOS_ID,
    DRIVE_FOLDER_LOCACAO_ID,
    DRIVE_FOLDER_MINUTAS_ID,
    DRIVE_SUBFOLDER_RH_CLT,
    DRIVE_SUBFOLDER_RH_PJ,
    MONDAY_TIPO_RH,
)
from classificacao_procons.contratos.drive_routing import (
    format_drive_folder_path,
    infer_category,
    infer_monday_tipo,
    is_rh_document,
    resolve_drive_destination,
)


class TestDriveRouting:
    def test_should_route_locacao_to_locacao_folder(self) -> None:
        category = infer_category(document_name="Aditivo Locação Imóvel - Tower Bridge")
        destination = resolve_drive_destination(
            document_name="Aditivo Locação Imóvel - Tower Bridge",
            counterparty_name="Tower Bridge",
            property_name="Tower Bridge",
        )
        assert category == "locacao"
        assert destination.root_folder_id == DRIVE_FOLDER_LOCACAO_ID
        assert destination.path_parts == ["Tower Bridge"]

    def test_should_route_minuta_b2b_to_minutas_folder(self) -> None:
        destination = resolve_drive_destination(
            document_name="Minuta Padrão Contrato B2B - Bloom Body",
            counterparty_name="Bloom Body",
        )
        assert destination.root_folder_id == DRIVE_FOLDER_MINUTAS_ID
        assert destination.path_parts[0] == "Comercial - B2B"

    def test_should_route_default_contract_to_contratos_folder(self) -> None:
        destination = resolve_drive_destination(
            document_name="Contrato B2B - Duda & Tina",
            counterparty_name="Duda & Tina",
        )
        assert destination.root_folder_id == DRIVE_FOLDER_CONTRATOS_ID
        assert destination.path_parts == ["Duda & Tina"]

    def test_should_route_influencer_contract_by_name(self) -> None:
        category = infer_category(document_name="Contrato Influencer - Theulyn Reis")
        assert category == "default"

    def test_should_route_rescisao_to_rh_clt_folder(self) -> None:
        document_name = "Termo de Rescisão - Carolinne Cristina Selles de Macedo 07 2026"
        category = infer_category(document_name=document_name)
        destination = resolve_drive_destination(
            document_name=document_name,
            counterparty_name="Carolinne Cristina Selles de Macedo",
        )
        assert category == "rh_clt"
        assert destination.root_folder_id == DRIVE_FOLDER_CONTRATOS_ID
        assert destination.path_parts == [
            DRIVE_SUBFOLDER_RH_CLT,
            "Carolinne Cristina Selles de Macedo",
        ]
        assert infer_monday_tipo(document_name=document_name, category=category) == MONDAY_TIPO_RH
        assert format_drive_folder_path(destination) == (
            "1 - Contratos / RH - CLT / Carolinne Cristina Selles de Macedo"
        )

    def test_should_route_pj_interno_to_rh_pj_folder(self) -> None:
        document_name = "Contrato PJ Interno - João Silva"
        category = infer_category(document_name=document_name)
        destination = resolve_drive_destination(
            document_name=document_name,
            counterparty_name="João Silva",
        )
        assert category == "rh_pj"
        assert destination.path_parts == [DRIVE_SUBFOLDER_RH_PJ, "João Silva"]
        assert infer_monday_tipo(document_name=document_name, category=category) == MONDAY_TIPO_RH

    @pytest.mark.parametrize(
        ("document_name", "expected_category"),
        [
            ("Código de Conduta - Maria Souza", "rh_clt"),
            ("Termo de Férias - Pedro Alves", "rh_clt"),
            ("TCE - Ana Costa 2026", "rh_clt"),
            ("Contrato de Trabalho - Lucas Mendes", "rh_clt"),
            ("Termo de Compromisso de Estágio - Julia Lima", "rh_clt"),
        ],
    )
    def test_should_classify_rh_documents_as_rh_tipo(
        self,
        document_name: str,
        expected_category: str,
    ) -> None:
        category = infer_category(document_name=document_name)
        assert category == expected_category
        assert is_rh_document(document_name=document_name) is True
        assert infer_monday_tipo(document_name=document_name, category=category) == MONDAY_TIPO_RH
