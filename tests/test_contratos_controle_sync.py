"""Testes de sincronização Controle Assinaturas."""

from datetime import date
from unittest.mock import patch

import pytest

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.controle_link_suggestions import LegacyAutoLinkResult
from classificacao_procons.contratos.controle_sync import sync_controle_from_autentique
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


def _empty_legacy_link() -> LegacyAutoLinkResult:
    return LegacyAutoLinkResult(
        applied=0,
        would_apply=0,
        ambiguous_skipped=0,
        failed=0,
        dry_run=False,
        items=(),
    )


class TestControleSync:
    @patch("classificacao_procons.contratos.controle_sync.find_controle_items_by_autentique_id")
    @patch("classificacao_procons.contratos.controle_sync.auto_link_unambiguous_legacy_controle")
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
        auto_link_mock,
        find_items_mock,
    ) -> None:
        find_items_mock.return_value = ()
        auto_link_mock.return_value = _empty_legacy_link()
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
            allow_create=True,
        )

        assert result.created == 1
        assert result.failed == 0
        assert create_item_mock.call_count == 2
        call_kwargs = create_item_mock.call_args_list[0].kwargs
        assert call_kwargs["item_name"] == "Contrato B2B - Empresa X"
        assert call_kwargs["status_label"] == "Assinado"
        assert call_kwargs["signed_at"] == date(2026, 1, 2)

    @patch("classificacao_procons.contratos.controle_sync.find_controle_items_by_autentique_id")
    @patch("classificacao_procons.contratos.controle_sync.auto_link_unambiguous_legacy_controle")
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
        auto_link_mock,
        find_items_mock,
    ) -> None:
        find_items_mock.return_value = ()
        auto_link_mock.return_value = _empty_legacy_link()
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
            allow_create=True,
        )

        for call in create_item_mock.call_args_list:
            assert call.kwargs["tipo_label"] is None

    @patch("classificacao_procons.contratos.controle_sync.ensure_controle_dual_tracks_for_document")
    @patch("classificacao_procons.contratos.controle_sync.find_controle_items_by_autentique_id")
    @patch("classificacao_procons.contratos.controle_sync.auto_link_unambiguous_legacy_controle")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_should_skip_existing_documents(
        self,
        list_documents_mock,
        build_index_mock,
        load_groups_mock,
        auto_link_mock,
        find_items_mock,
        repair_mock,
    ) -> None:
        find_items_mock.return_value = (
            ControleAssinaturasItem(
                item_id="1",
                name="Contrato existente",
                status=None,
                tipo=None,
                signature_link="Autentique ID: doc-1",
            ),
        )
        auto_link_mock.return_value = _empty_legacy_link()
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
            allow_create=True,
        )

        assert result.created == 0
        assert result.already_in_monday == 1


class TestControleSyncCreatePaused:
    @patch("classificacao_procons.contratos.controle_sync.find_controle_items_by_autentique_id")
    @patch("classificacao_procons.contratos.controle_sync.auto_link_unambiguous_legacy_controle")
    @patch("classificacao_procons.contratos.controle_sync.create_controle_assinatura_item")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_should_not_create_when_pause_active(
        self,
        list_documents_mock,
        build_index_mock,
        load_groups_mock,
        create_item_mock,
        auto_link_mock,
        find_items_mock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CONTROLE_PAUSE_CREATE", "true")
        find_items_mock.return_value = ()
        auto_link_mock.return_value = _empty_legacy_link()
        document = AutentiqueDocumentSummary(
            document_id="doc-new",
            name="Contrato novo",
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

        result = sync_controle_from_autentique(
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
            dry_run=False,
        )

        assert result.created == 0
        assert result.create_paused == 1
        create_item_mock.assert_not_called()
        assert result.items[0].action == "create_paused"
