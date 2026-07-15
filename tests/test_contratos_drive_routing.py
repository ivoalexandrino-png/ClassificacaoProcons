"""Testes de roteamento de pastas do Drive para contratos."""

from classificacao_procons.contratos.constants import (
    DRIVE_FOLDER_CONTRATOS_ID,
    DRIVE_FOLDER_LOCACAO_ID,
    DRIVE_FOLDER_MINUTAS_ID,
    DRIVE_SUBFOLDER_RH_CLT,
)
from classificacao_procons.contratos.drive_routing import (
    format_drive_folder_path,
    infer_category,
    infer_monday_tipo,
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
        assert infer_monday_tipo(document_name=document_name, category=category) == (
            "Contratos de Trabalho (CLT)"
        )
        assert format_drive_folder_path(destination) == (
            "1 - Contratos / RH - CLT / Carolinne Cristina Selles de Macedo"
        )
