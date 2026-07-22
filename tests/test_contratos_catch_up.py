"""Testes do catch-up em lote de contratos."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from classificacao_procons.contratos.autentique.client import AutentiqueDocumentSummary
from classificacao_procons.contratos.catch_up import catch_up_contratos
from classificacao_procons.contratos.controle_sync import ControleSyncResult
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.pipeline import ContractPipelineResult


def _signed_document(*, document_id: str, name: str) -> AutentiqueDocumentSummary:
    return AutentiqueDocumentSummary(
        document_id=document_id,
        name=name,
        created_at="2026-01-01",
        signed_pdf_url="https://example.com/signed.pdf",
        signatures=(),
    )


class TestCatchUpContratos:
    @patch("classificacao_procons.contratos.catch_up.find_controle_item_by_autentique_id")
    @patch("classificacao_procons.contratos.catch_up.process_finished_document")
    @patch("classificacao_procons.contratos.catch_up.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.catch_up.list_documents")
    @patch("classificacao_procons.contratos.catch_up.sync_controle_from_autentique")
    def test_should_process_signed_documents_not_yet_in_contratos(
        self,
        sync_mock,
        list_mock,
        index_mock,
        process_mock,
        find_mock,
    ) -> None:
        sync_mock.return_value = ControleSyncResult(
            total_autentique=1,
            already_in_monday=0,
            created=1,
            updated=0,
            skipped=0,
            failed=0,
            dry_run=False,
            items=(),
        )
        document = _signed_document(document_id="doc-1", name="Contrato A")
        list_mock.return_value = [document]
        index_mock.return_value = MagicMock(get_item=lambda _document_id: None)
        find_mock.return_value = None
        process_mock.return_value = ContractPipelineResult(
            document_id="doc-1",
            document_name="Contrato A",
            drive_pdf_url="https://drive.example/doc.pdf",
            drive_folder_path="Contratos/Fornecedores",
            controle_item_id="100",
            contratos_item_id="200",
            contratos_item_url="https://monday.example/200",
        )

        result = catch_up_contratos(
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
            dry_run=False,
            max_pages=1,
        )

        assert result.sync_created == 1
        assert result.signed_total == 1
        assert result.processed == 1
        assert result.process_failed == 0
        process_mock.assert_called_once()

    @patch("classificacao_procons.contratos.catch_up.process_finished_document")
    @patch("classificacao_procons.contratos.catch_up.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.catch_up.list_documents")
    @patch("classificacao_procons.contratos.catch_up.sync_controle_from_autentique")
    def test_should_skip_when_already_linked_in_contratos(
        self,
        sync_mock,
        list_mock,
        index_mock,
        process_mock,
    ) -> None:
        sync_mock.return_value = ControleSyncResult(
            total_autentique=1,
            already_in_monday=1,
            created=0,
            updated=0,
            skipped=0,
            failed=0,
            dry_run=False,
            items=(),
        )
        document = _signed_document(document_id="doc-2", name="Contrato B")
        list_mock.return_value = [document]
        index_mock.return_value = MagicMock(
            get_item=lambda _document_id: ControleAssinaturasItem(
                item_id="101",
                name="Contrato B",
                status="Assinado",
                tipo="Fornecedor",
                signature_link=None,
                related_contract_item_ids=("555",),
            ),
        )

        result = catch_up_contratos(
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
            dry_run=False,
            max_pages=1,
        )

        assert result.skipped == 1
        assert result.processed == 0
        process_mock.assert_not_called()

    @patch("classificacao_procons.contratos.catch_up.find_controle_item_by_autentique_id")
    @patch("classificacao_procons.contratos.catch_up.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.catch_up.list_documents")
    @patch("classificacao_procons.contratos.catch_up.sync_controle_from_autentique")
    def test_should_support_dry_run_without_processing(
        self,
        sync_mock,
        list_mock,
        index_mock,
        find_mock,
    ) -> None:
        sync_mock.return_value = ControleSyncResult(
            total_autentique=1,
            already_in_monday=0,
            created=1,
            updated=0,
            skipped=0,
            failed=0,
            dry_run=True,
            items=(),
        )
        list_mock.return_value = [_signed_document(document_id="doc-3", name="Contrato C")]
        index_mock.return_value = MagicMock(get_item=lambda _document_id: None)
        find_mock.return_value = None

        result = catch_up_contratos(
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
            dry_run=True,
            max_pages=1,
        )

        assert result.dry_run is True
        assert result.processed == 1
        assert result.items[0].action == "would_process"
