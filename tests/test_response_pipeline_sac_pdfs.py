"""Elaboração com PDFs do SAC (sem .txt obrigatório)."""

from unittest.mock import patch

from classificacao_procons.drive.reader import DriveFileInfo, SacFolderContext
from classificacao_procons.gemini.client import GeneratedResponse
from classificacao_procons.models import MondayCaseReady
from classificacao_procons.response_pipeline import (
    ResponsePipelineOptions,
    elaborate_pending_responses,
)


@patch("classificacao_procons.response_pipeline.update_elaborated_response_links")
@patch("classificacao_procons.response_pipeline.upload_pdf_file", return_value="https://drive/u")
@patch("classificacao_procons.response_pipeline.upload_text_file", return_value="https://drive/t")
@patch("classificacao_procons.response_pipeline.ensure_output_folder", return_value="out")
@patch("classificacao_procons.response_pipeline.build_unified_response_pdf")
@patch("classificacao_procons.response_pipeline.generate_procon_response")
@patch("classificacao_procons.response_pipeline.find_existing_response_outputs", return_value=None)
@patch("classificacao_procons.response_pipeline.download_drive_file")
@patch("classificacao_procons.response_pipeline.resolve_sac_folder_context")
@patch("classificacao_procons.response_pipeline.list_cases_ready_for_elaboration")
@patch("classificacao_procons.response_pipeline.has_valid_token", return_value=True)
def test_should_elaborate_when_sac_folder_has_only_pdfs(
    _token_mock,
    list_cases_mock,
    resolve_sac_mock,
    download_mock,
    _find_existing_mock,
    generate_mock,
    _build_pdf_mock,
    _ensure_mock,
    _upload_text_mock,
    _upload_pdf_mock,
    _update_monday_mock,
    tmp_path,
) -> None:
    list_cases_mock.return_value = [
        MondayCaseReady(
            item_id="200",
            item_name="ANGELICA SANTOS",
            docs_sac_url="https://drive.google.com/drive/folders/abc",
            protocol_number="1656146/2026",
        ),
    ]
    resolve_sac_mock.return_value = SacFolderContext(
        consumer_folder_id="folder-consumer",
        sac_folder_id="folder-sac",
        complaint_pdf=DriveFileInfo(
            "pdf-cip",
            "Reclamacao.pdf",
            "application/pdf",
            None,
        ),
        summary_txt=None,
        supporting_files=[
            DriveFileInfo("pdf-sac", "Tratativa zendesk.pdf", "application/pdf", None),
        ],
    )

    def fake_download(*, file_id: str, destination, token_path=None):
        destination.parent.mkdir(parents=True, exist_ok=True)
        if file_id == "pdf-sac":
            destination.write_text("Cliente cancelou assinatura.", encoding="utf-8")
        else:
            destination.write_bytes(b"%PDF-1.4")
        return destination

    download_mock.side_effect = fake_download

    with patch(
        "classificacao_procons.response_pipeline.build_sac_summary_from_drive_files",
        return_value="### Tratativa zendesk.pdf\nCliente cancelou assinatura.",
    ):
        generate_mock.return_value = GeneratedResponse(
            analysis="A",
            draft="B",
            final_response="Resposta",
            portal_summary="Resumo",
        )
        results = elaborate_pending_responses(
            ResponsePipelineOptions(
                work_dir=tmp_path / "work",
                state_path=tmp_path / "state.json",
                monday_api_token="token",
                gemini_api_key="key",
            ),
        )

    assert results[0].status == "success"
    generate_mock.assert_called_once()
    assert "cancelou" in generate_mock.call_args.kwargs["sac_summary"]
