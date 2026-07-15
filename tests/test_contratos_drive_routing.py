"""Testes de roteamento de pastas do Drive para contratos."""

from classificacao_procons.contratos.constants import (
    DRIVE_FOLDER_CONTRATOS_ID,
    DRIVE_FOLDER_LOCACAO_ID,
    DRIVE_FOLDER_MINUTAS_ID,
)
from classificacao_procons.contratos.drive_routing import (
    infer_category,
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
