"""Testes de reconcile-controle-mismatches (compare divergences only)."""

from unittest.mock import patch

from classificacao_procons.contratos.autentique.client import AutentiqueDocumentSummary
from classificacao_procons.contratos.controle_sync import (
    ControleReconcileResult,
    _monday_inactive_item_error,
    reconcile_controle_compare_mismatches,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex
from classificacao_procons.monday.client import MondayClientError


def _sample_document() -> AutentiqueDocumentSummary:
    return AutentiqueDocumentSummary(
        document_id="doc-mismatch",
        name="Contrato Teste",
        created_at="2026-08-01",
        signed_pdf_url=None,
        signatures=(),
    )


class TestMondayInactiveItemError:
    def test_should_detect_inactive_items_message(self) -> None:
        assert _monday_inactive_item_error(
            MondayClientError("Cannot change column value for inactive items"),
        )

    def test_should_not_treat_other_errors_as_inactive(self) -> None:
        assert not _monday_inactive_item_error(MondayClientError("rate limit"))


class TestReconcileControleCompareMismatches:
    @patch("classificacao_procons.contratos.controle_sync.reconcile_controle_from_document")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    @patch(
        "classificacao_procons.contratos.controle_sync.find_monday_status_behind_autentique",
    )
    @patch(
        "classificacao_procons.contratos.controle_sync.find_monday_track_status_mismatch",
    )
    def test_should_reconcile_only_compare_mismatch_documents(
        self,
        track_mismatch_mock,
        status_behind_mock,
        list_documents_mock,
        build_index_mock,
        load_groups_mock,
        reconcile_mock,
    ) -> None:
        document = _sample_document()
        item = ControleAssinaturasItem(
            item_id="999",
            name=document.name,
            status="Aguardando assinatura",
            tipo="Contratos B2B",
            signature_link="Autentique ID: doc-mismatch",
            group_id="group-jan",
        )
        list_documents_mock.return_value = [document]
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset({"doc-mismatch"}),
            exact_names=frozenset(),
            items_by_document_id=(("doc-mismatch", item),),
            all_items=(item,),
        )
        load_groups_mock.return_value = {"jan": "group-jan"}
        track_mismatch_mock.return_value = (
            ("999", document.name, "doc-mismatch", None, "jan"),
        )
        status_behind_mock.return_value = ()
        reconcile_mock.return_value = ControleReconcileResult(
            document_id=document.document_id,
            document_name=document.name,
            monday_item_id="999",
            updated=True,
            skipped=False,
            group_id="group-jan",
            status_label="Aguardando outros",
        )

        result = reconcile_controle_compare_mismatches(
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
            dry_run=False,
            include_status_behind=True,
        )

        assert result.track_mismatch_documents == 1
        assert result.status_behind_documents == 0
        assert result.updated == 1
        assert result.failed == 0
        reconcile_mock.assert_called_once()

    @patch("classificacao_procons.contratos.controle_sync.reconcile_controle_from_document")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    @patch(
        "classificacao_procons.contratos.controle_sync.find_monday_status_behind_autentique",
    )
    @patch(
        "classificacao_procons.contratos.controle_sync.find_monday_track_status_mismatch",
    )
    def test_should_skip_inactive_monday_items_without_counting_as_failed(
        self,
        track_mismatch_mock,
        status_behind_mock,
        list_documents_mock,
        build_index_mock,
        load_groups_mock,
        reconcile_mock,
    ) -> None:
        document = _sample_document()
        item = ControleAssinaturasItem(
            item_id="888",
            name=document.name,
            status="Assinado",
            tipo=None,
            signature_link="Autentique ID: doc-mismatch",
            group_id="group-luciano",
        )
        list_documents_mock.return_value = [document]
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset({"doc-mismatch"}),
            exact_names=frozenset(),
            items_by_document_id=(("doc-mismatch", item),),
            all_items=(item,),
        )
        load_groups_mock.return_value = {}
        track_mismatch_mock.return_value = (
            ("888", document.name, "doc-mismatch", None, "luciano"),
        )
        status_behind_mock.return_value = ()
        reconcile_mock.side_effect = MondayClientError(
            "Cannot change column value for inactive items",
        )

        result = reconcile_controle_compare_mismatches(
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
        )

        assert result.failed == 0
        assert result.skipped == 1
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    @patch("classificacao_procons.contratos.controle_sync.fetch_document_summary")
    def test_should_use_light_feed_without_list_documents(
        self,
        fetch_mock,
        list_documents_mock,
    ) -> None:
        from classificacao_procons.contratos.controle_sync import (
            _documents_by_id_for_controle_reconcile,
        )

        doc_id = "a" * 48
        item = ControleAssinaturasItem(
            item_id="1",
            name="Doc",
            status=None,
            tipo=None,
            signature_link=f"Autentique ID: {doc_id}",
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset({doc_id}),
            exact_names=frozenset(),
            all_items=(item,),
        )
        fetch_mock.return_value = AutentiqueDocumentSummary(
            document_id=doc_id,
            name="Doc",
            created_at=None,
            signed_pdf_url=None,
            signatures=(),
        )

        result = _documents_by_id_for_controle_reconcile(
            index=index,
            autentique_api_token="token",
            max_pages=50,
            light_feed=True,
        )

        list_documents_mock.assert_not_called()
        fetch_mock.assert_called_once()
        assert doc_id in result
