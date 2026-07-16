"""Testes do pipeline de contratos."""

import json
from pathlib import Path
from unittest.mock import patch

from classificacao_procons.contratos.autentique.webhook import AutentiqueWebhookEvent
from classificacao_procons.contratos.pipeline import (
    ContractPipelineOptions,
    process_finished_document,
    process_finished_webhook_event,
)


class TestContractPipeline:
    @patch("classificacao_procons.contratos.pipeline.register_contrato_subitem")
    @patch("classificacao_procons.contratos.pipeline.update_controle_assinado")
    @patch("classificacao_procons.contratos.pipeline.find_controle_item")
    @patch("classificacao_procons.contratos.pipeline.upload_pdf_to_folder_path")
    @patch("classificacao_procons.contratos.pipeline.download_file")
    @patch("classificacao_procons.contratos.pipeline.extract_contract_metadata")
    def test_should_process_finished_document_with_monday_automation(
        self,
        extract_mock,
        download_mock,
        upload_mock,
        find_controle_mock,
        update_controle_mock,
        register_subitem_mock,
        tmp_path: Path,
    ) -> None:
        from classificacao_procons.contratos.gemini_extractor import ContractMetadata
        from classificacao_procons.contratos.monday_contracts import ControleAssinaturasItem

        pdf_path = tmp_path / "downloads" / "contratos" / "doc-1.pdf"
        pdf_path.parent.mkdir(parents=True)
        pdf_path.write_bytes(b"%PDF-1.4")

        extract_mock.return_value = ContractMetadata(
            counterparty_name="Duda & Tina",
            counterparty_cnpj="12.345.678/0001-90",
            contract_type="B2B",
            company="B4A",
            start_date=None,
            end_date=None,
            property_name=None,
            summary="Contrato B2B",
        )
        download_mock.return_value = pdf_path
        upload_mock.return_value = ("folder", "https://drive/folder", "https://drive/file.pdf")
        find_controle_mock.return_value = ControleAssinaturasItem(
            item_id="111",
            name="Contrato B2B - Duda & Tina",
            status="Aguardando Assinatura",
            tipo="Contratos B2B",
            signature_link="https://assina.ae/abc",
        )

        state_path = tmp_path / "processed.json"
        result = process_finished_document(
            document_id="doc-1",
            document_name="Contrato B2B - Duda & Tina",
            signed_pdf_url="https://example.com/signed.pdf",
            options=ContractPipelineOptions(
                download_dir=tmp_path / "downloads" / "contratos",
                state_path=state_path,
                monday_api_token="token",
            ),
        )

        assert result.drive_pdf_url == "https://drive/file.pdf"
        assert result.drive_folder_path == "1 - Contratos / Duda & Tina"
        assert result.controle_item_id == "111"
        assert result.contratos_item_id is None
        assert result.contratos_registration_mode == "monday_automation"
        update_controle_mock.assert_called_once()
        register_subitem_mock.assert_not_called()

        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert "doc-1" in state["document_ids"]

    @patch("classificacao_procons.contratos.pipeline.register_contrato_subitem")
    @patch("classificacao_procons.contratos.pipeline.resolve_parent_contrato_item")
    @patch("classificacao_procons.contratos.pipeline.update_controle_assinado")
    @patch("classificacao_procons.contratos.pipeline.find_controle_item")
    @patch("classificacao_procons.contratos.pipeline.upload_pdf_to_folder_path")
    @patch("classificacao_procons.contratos.pipeline.download_file")
    @patch("classificacao_procons.contratos.pipeline.extract_contract_metadata")
    def test_should_create_subitem_when_controle_tipo_is_empty(
        self,
        extract_mock,
        download_mock,
        upload_mock,
        find_controle_mock,
        update_controle_mock,
        resolve_parent_mock,
        register_subitem_mock,
        tmp_path: Path,
    ) -> None:
        from classificacao_procons.contratos.gemini_extractor import ContractMetadata
        from classificacao_procons.contratos.monday_contracts import (
            ControleAssinaturasItem,
            MondayContractRegistrationResult,
        )
        from classificacao_procons.contratos.parent_resolver import ParentResolutionResult

        pdf_path = tmp_path / "downloads" / "contratos" / "doc-2.pdf"
        pdf_path.parent.mkdir(parents=True)
        pdf_path.write_bytes(b"%PDF-1.4")

        extract_mock.return_value = ContractMetadata(
            counterparty_name="Tower Bridge",
            counterparty_cnpj=None,
            contract_type="Aditivo",
            company="B4A",
            start_date=None,
            end_date=None,
            property_name="Tower Bridge",
            summary=None,
        )
        download_mock.return_value = pdf_path
        upload_mock.return_value = ("folder", "https://drive/folder", "https://drive/file.pdf")
        find_controle_mock.return_value = ControleAssinaturasItem(
            item_id="112",
            name="Aditivo Locação Imóvel - Tower Bridge",
            status="Aguardando Assinatura",
            tipo=None,
            signature_link="https://assina.ae/aditivo",
        )
        resolve_parent_mock.return_value = ParentResolutionResult(
            parent_item_id="200",
            strategy="gemini_reference",
        )
        register_subitem_mock.return_value = MondayContractRegistrationResult(
            controle_item_id=None,
            contratos_item_id="999",
            contratos_item_url="https://monday/item/999",
            registration_mode="subitem",
            parent_item_id="200",
        )

        result = process_finished_document(
            document_id="doc-2",
            document_name="Aditivo Locação Imóvel - Tower Bridge",
            signed_pdf_url="https://example.com/signed.pdf",
            options=ContractPipelineOptions(
                download_dir=tmp_path / "downloads" / "contratos",
                state_path=tmp_path / "processed.json",
                monday_api_token="token",
            ),
        )

        assert result.contratos_item_id == "999"
        assert result.contratos_parent_item_id == "200"
        assert result.contratos_parent_resolution_strategy == "gemini_reference"
        assert result.contratos_registration_mode == "subitem"
        resolve_parent_mock.assert_called_once()
        register_subitem_mock.assert_called_once()

    def test_should_skip_duplicate_document(self, tmp_path: Path) -> None:
        state_path = tmp_path / "processed.json"
        state_path.write_text(
            json.dumps({"document_ids": ["doc-1"]}),
            encoding="utf-8",
        )
        result = process_finished_document(
            document_id="doc-1",
            document_name="Contrato",
            signed_pdf_url="https://example.com/signed.pdf",
            options=ContractPipelineOptions(state_path=state_path, monday_api_token="token"),
        )
        assert result.skipped_duplicate is True

    def test_should_reject_unsupported_webhook_event(self) -> None:
        event = AutentiqueWebhookEvent(
            event_id="evt",
            event_type="signature.accepted",
            document_id="doc",
            document_name="Nome",
            signed_pdf_url=None,
        )
        try:
            process_finished_webhook_event(event)
        except Exception as exc:
            assert "não suportado" in str(exc).lower()
            return
        raise AssertionError("expected unsupported event error")
