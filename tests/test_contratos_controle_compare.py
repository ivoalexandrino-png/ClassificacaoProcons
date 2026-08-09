"""Testes de comparação e sync seguro Controle Assinaturas."""

from unittest.mock import patch

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.controle_link_suggestions import LegacyAutoLinkResult
from classificacao_procons.contratos.controle_sync import (
    compare_autentique_with_controle,
    sync_controle_from_autentique,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


class TestControleCompare:
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_should_list_pending_missing_in_monday(
        self,
        list_documents_mock,
        build_index_mock,
    ) -> None:
        pending = AutentiqueDocumentSummary(
            document_id="pending-1",
            name="Contrato pendente",
            created_at=None,
            signed_pdf_url=None,
            signatures=(
                AutentiqueSigner(
                    public_id="s1",
                    name="Jan",
                    email="jan@example.com",
                    short_link="https://assina.ae/x",
                    signed_at=None,
                ),
            ),
        )
        list_documents_mock.return_value = [pending]
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset(),
            all_items=(),
        )

        result = compare_autentique_with_controle(
            monday_api_token="token",
            autentique_api_token="token",
        )

        assert result.pending_missing_in_monday == (("pending-1", "Contrato pendente"),)
        assert result.signed_missing_in_monday == ()

    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_should_include_legacy_link_suggestions_in_compare(
        self,
        list_documents_mock,
        build_index_mock,
    ) -> None:
        title = "Contrato B2B - Legado Match"
        legacy = ControleAssinaturasItem(
            item_id="legacy-1",
            name=title,
            status="Aguardando Assinatura",
            tipo=None,
            signature_link="https://assina.ae/old",
        )
        pending = AutentiqueDocumentSummary(
            document_id="pending-link",
            name=title,
            created_at=None,
            signed_pdf_url=None,
            signatures=(
                AutentiqueSigner(
                    public_id="s1",
                    name="Jan",
                    email="jan@example.com",
                    short_link="https://assina.ae/x",
                    signed_at=None,
                ),
            ),
        )
        list_documents_mock.return_value = [pending]
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset({title.casefold()}),
            all_items=(legacy,),
        )

        result = compare_autentique_with_controle(
            monday_api_token="token",
            autentique_api_token="token",
        )

        assert len(result.legacy_link_suggestions) == 1
        assert result.legacy_link_suggestions[0].monday_item_id == "legacy-1"
        assert result.legacy_link_suggestions[0].autentique_document_id == "pending-link"


class TestControleSyncSkipSigned:
    @patch("classificacao_procons.contratos.controle_sync.ensure_autentique_id_on_controle_items")
    @patch("classificacao_procons.contratos.controle_sync.reconcile_controle_from_document")
    @patch("classificacao_procons.contratos.controle_sync.ensure_controle_dual_tracks_for_document")
    @patch("classificacao_procons.contratos.controle_sync.find_controle_items_by_autentique_id")
    @patch("classificacao_procons.contratos.controle_sync.auto_link_unambiguous_legacy_controle")
    @patch("classificacao_procons.contratos.controle_sync.create_controle_assinatura_item")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_should_defer_fully_signed_when_skip_signed_documents(
        self,
        list_documents_mock,
        build_index_mock,
        load_groups_mock,
        create_item_mock,
        auto_link_mock,
        find_items_mock,
        repair_mock,
        reconcile_mock,
        link_mock,
    ) -> None:
        find_items_mock.return_value = ()
        auto_link_mock.return_value = LegacyAutoLinkResult(
            applied=0,
            would_apply=0,
            ambiguous_skipped=0,
            failed=0,
            dry_run=False,
            items=(),
        )
        signed = AutentiqueDocumentSummary(
            document_id="signed-1",
            name="Contrato assinado",
            created_at=None,
            signed_pdf_url="https://example.com/s.pdf",
            signatures=(
                AutentiqueSigner(
                    public_id="s1",
                    name="Jan",
                    email="jan@example.com",
                    short_link="https://assina.ae/x",
                    signed_at="2026-01-01T00:00:00Z",
                ),
            ),
        )
        list_documents_mock.return_value = [signed]
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset(),
        )
        load_groups_mock.return_value = {
            "assinados": "novo_grupo",
            "contratos pendentes de assinatura jan": "group-jan",
            "contratos pendentes de assinatura luciano": "group-luciano",
        }
        from classificacao_procons.contratos.controle_sync import ControleReconcileResult

        reconcile_mock.return_value = ControleReconcileResult(
            document_id="signed-1",
            document_name="Contrato assinado",
            monday_item_id="legacy-1",
            updated=True,
            skipped=False,
            group_id="novo_grupo",
            status_label="Assinado",
        )

        result = sync_controle_from_autentique(
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
            dry_run=False,
            skip_signed_documents=True,
        )

        assert result.created == 0
        assert result.deferred_signed == 1
        create_item_mock.assert_not_called()

    @patch("classificacao_procons.contratos.controle_sync.ensure_autentique_id_on_controle_items")
    @patch("classificacao_procons.contratos.controle_sync.reconcile_controle_from_document")
    @patch("classificacao_procons.contratos.controle_sync.ensure_controle_dual_tracks_for_document")
    @patch("classificacao_procons.contratos.controle_sync.find_controle_items_by_autentique_id")
    @patch("classificacao_procons.contratos.controle_sync.auto_link_unambiguous_legacy_controle")
    @patch("classificacao_procons.contratos.controle_sync.create_controle_assinatura_item")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_should_link_signed_legacy_when_skip_signed_documents(
        self,
        list_documents_mock,
        build_index_mock,
        load_groups_mock,
        create_item_mock,
        auto_link_mock,
        find_items_mock,
        repair_mock,
        reconcile_mock,
        link_mock,
    ) -> None:
        from classificacao_procons.contratos.constants import CONTROLE_STATUS_ASSINADO
        from classificacao_procons.contratos.controle_sync import ControleReconcileResult

        find_items_mock.return_value = ()
        auto_link_mock.return_value = LegacyAutoLinkResult(
            applied=0,
            would_apply=0,
            ambiguous_skipped=0,
            failed=0,
            dry_run=False,
            items=(),
        )
        title = "Contrato assinado legado"
        signed = AutentiqueDocumentSummary(
            document_id="signed-legacy",
            name=title,
            created_at=None,
            signed_pdf_url="https://example.com/s.pdf",
            signatures=(
                AutentiqueSigner(
                    public_id="s1",
                    name="Jan",
                    email="jan@example.com",
                    short_link="https://assina.ae/x",
                    signed_at="2026-01-01T00:00:00Z",
                ),
            ),
        )
        legacy = ControleAssinaturasItem(
            item_id="legacy-1",
            name=title,
            status=CONTROLE_STATUS_ASSINADO,
            tipo="Contratos B2B",
            signature_link="https://assina.ae/old",
        )
        list_documents_mock.return_value = [signed]
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset({title.casefold()}),
            all_items=(legacy,),
        )
        load_groups_mock.return_value = {
            "assinados": "novo_grupo",
            "contratos pendentes de assinatura jan": "group-jan",
            "contratos pendentes de assinatura luciano": "group-luciano",
        }
        reconcile_mock.return_value = ControleReconcileResult(
            document_id="signed-legacy",
            document_name=title,
            monday_item_id="legacy-1",
            updated=True,
            skipped=False,
            group_id="novo_grupo",
            status_label=CONTROLE_STATUS_ASSINADO,
        )

        result = sync_controle_from_autentique(
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
            dry_run=False,
            skip_signed_documents=True,
            allow_create=True,
        )

        assert result.created == 0
        assert result.deferred_signed == 0
        assert result.updated == 1
        link_mock.assert_called_once()
        create_item_mock.assert_not_called()
