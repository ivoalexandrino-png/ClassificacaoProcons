"""Testes de sincronização Controle Assinaturas."""

from datetime import date
from unittest.mock import patch

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.controle_sync import sync_controle_from_autentique
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


class TestControleSync:
    @patch("classificacao_procons.contratos.controle_sync.create_controle_assinatura_item")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_should_create_missing_documents(
        self,
        list_documents_mock,
        build_index_mock,
        load_groups_mock,
        create_item_mock,
    ) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-1",
            name="Contrato B2B - Empresa X",
            created_at="2026-01-01",
            signed_pdf_url="https://example.com/signed.pdf",
            signatures=(
                AutentiqueSigner(
                    public_id="sig-1",
                    name="Jan",
                    email="jan@example.com",
                    short_link="https://assina.ae/abc",
                    signed_at="2026-01-02T10:00:00Z",
                ),
            ),
        )
        list_documents_mock.return_value = [document]
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset(),
        )
        load_groups_mock.return_value = {
            "assinados": "novo_grupo",
            "contratos pendentes de assinatura jan": "group-jan",
            "contratos pendentes de assinatura luciano": "group-luciano",
        }
        create_item_mock.side_effect = [
            ("111", "https://monday/item/111"),
            ("112", "https://monday/item/112"),
        ]

        result = sync_controle_from_autentique(
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
            dry_run=False,
        )

        assert result.created == 1
        assert result.failed == 0
        assert create_item_mock.call_count == 2
        call_kwargs = create_item_mock.call_args_list[0].kwargs
        assert call_kwargs["item_name"] == "Contrato B2B - Empresa X"
        assert call_kwargs["status_label"] == "Assinado"
        assert call_kwargs["signed_at"] == date(2026, 1, 2)

    @patch("classificacao_procons.contratos.controle_sync.create_controle_assinatura_item")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_should_not_fill_tipo_for_supplemental_documents(
        self,
        list_documents_mock,
        build_index_mock,
        load_groups_mock,
        create_item_mock,
    ) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-aditivo",
            name="Aditivo Locação Imóvel - Tower Bridge",
            created_at="2026-01-01",
            signed_pdf_url=None,
            signatures=(),
        )
        list_documents_mock.return_value = [document]
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset(),
        )
        load_groups_mock.return_value = {
            "assinados": "novo_grupo",
            "contratos pendentes de assinatura jan": "group-jan",
            "contratos pendentes de assinatura luciano": "group-luciano",
        }
        create_item_mock.side_effect = [("222", None), ("223", None)]

        sync_controle_from_autentique(
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
            dry_run=False,
        )

        for call in create_item_mock.call_args_list:
            assert call.kwargs["tipo_label"] is None

    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_should_skip_existing_documents(
        self,
        list_documents_mock,
        build_index_mock,
        load_groups_mock,
    ) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-1",
            name="Contrato existente",
            created_at=None,
            signed_pdf_url=None,
            signatures=(),
        )
        list_documents_mock.return_value = [document]
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset({"doc-1"}),
            exact_names=frozenset(),
        )
        load_groups_mock.return_value = {"assinados": "novo_grupo"}

        result = sync_controle_from_autentique(
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
            dry_run=False,
        )

        assert result.created == 0
        assert result.already_in_monday == 1
