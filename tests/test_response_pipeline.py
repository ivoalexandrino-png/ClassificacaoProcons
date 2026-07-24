"""Testes do pipeline de elaboração de resposta."""

from unittest.mock import patch

from classificacao_procons.drive.reader import DriveFileInfo, SacFolderContext
from classificacao_procons.gemini.client import GeneratedResponse
from classificacao_procons.models import MondayCaseReady
from classificacao_procons.response_pipeline import (
    ResponsePipelineOptions,
    elaborate_pending_responses,
)


@patch("classificacao_procons.response_pipeline.update_elaborated_response_links")
@patch("classificacao_procons.response_pipeline.upload_pdf_file")
@patch("classificacao_procons.response_pipeline.upload_text_file")
@patch("classificacao_procons.response_pipeline.ensure_output_folder")
@patch("classificacao_procons.response_pipeline.build_unified_response_pdf")
@patch("classificacao_procons.response_pipeline.generate_procon_response")
@patch("classificacao_procons.response_pipeline.find_existing_response_outputs", return_value=None)
@patch("classificacao_procons.response_pipeline.download_drive_file")
@patch("classificacao_procons.response_pipeline.resolve_sac_folder_context")
@patch("classificacao_procons.response_pipeline.list_cases_ready_for_elaboration")
@patch("classificacao_procons.response_pipeline.has_valid_token", return_value=True)
def test_should_elaborate_response_for_monday_case(
    _token_mock,
    list_cases_mock,
    resolve_sac_mock,
    download_mock,
    _find_existing_mock,
    generate_mock,
    build_pdf_mock,
    ensure_folder_mock,
    upload_text_mock,
    upload_pdf_mock,
    update_monday_mock,
    tmp_path,
) -> None:
    list_cases_mock.return_value = [
        MondayCaseReady(
            item_id="100",
            item_name="MARIA SILVA",
            docs_sac_url="https://drive.google.com/drive/folders/abc",
            protocol_number="1653213/2026",
        ),
    ]
    resolve_sac_mock.return_value = SacFolderContext(
        consumer_folder_id="folder-consumer",
        sac_folder_id="folder-sac",
        complaint_pdf=DriveFileInfo(
            "pdf-1",
            "Atendimento Procon - MARIA.pdf",
            "application/pdf",
            None,
        ),
        summary_txt=DriveFileInfo("txt-1", "informacoes.txt", "text/plain", None),
        supporting_files=[
            DriveFileInfo("img-1", "comprovante.png", "image/png", None),
        ],
    )

    def fake_download(*, file_id: str, destination, token_path=None):
        destination.parent.mkdir(parents=True, exist_ok=True)
        if file_id == "txt-1":
            destination.write_text("Cliente recebeu o produto.", encoding="utf-8")
        else:
            destination.write_bytes(b"%PDF-1.4")
        return destination

    download_mock.side_effect = fake_download
    generate_mock.return_value = GeneratedResponse(
        analysis="Análise",
        draft="Rascunho",
        final_response="Resposta final",
        portal_summary="Resumo curto",
    )
    build_pdf_mock.return_value = tmp_path / "work" / "100" / "resposta-unificada.pdf"
    ensure_folder_mock.return_value = "folder-output"
    upload_text_mock.side_effect = [
        "https://drive/full",
        "https://drive/summary",
    ]
    upload_pdf_mock.return_value = "https://drive/unified"

    options = ResponsePipelineOptions(
        work_dir=tmp_path / "work",
        state_path=tmp_path / "state.json",
        monday_api_token="token-test",
        gemini_api_key="gemini-test",
    )
    results = elaborate_pending_responses(options)

    assert len(results) == 1
    assert results[0].status == "success"
    assert results[0].full_response_file_url == "https://drive/full"
    assert results[0].summary_response_file_url == "https://drive/summary"
    assert results[0].unified_pdf_file_url == "https://drive/unified"
    assert results[0].analysis_file_url is None
    generate_mock.assert_called_once()
    build_pdf_mock.assert_called_once()
    assert upload_text_mock.call_count == 2
    upload_pdf_mock.assert_called_once()
    update_monday_mock.assert_called_once()


@patch("classificacao_procons.response_pipeline.update_elaborated_response_links")
@patch("classificacao_procons.response_pipeline.generate_procon_response")
@patch("classificacao_procons.response_pipeline.find_existing_response_outputs")
@patch("classificacao_procons.response_pipeline.resolve_sac_folder_context")
@patch("classificacao_procons.response_pipeline.list_cases_ready_for_elaboration")
@patch("classificacao_procons.response_pipeline.has_valid_token", return_value=True)
def test_should_skip_when_response_files_already_exist_on_drive(
    _token_mock,
    list_cases_mock,
    resolve_sac_mock,
    find_existing_mock,
    generate_mock,
    update_monday_mock,
    tmp_path,
) -> None:
    from classificacao_procons.drive.reader import (
        DriveFileInfo,
        ExistingResponseOutputs,
        SacFolderContext,
    )

    list_cases_mock.return_value = [
        MondayCaseReady(
            item_id="100",
            item_name="MARIA SILVA",
            docs_sac_url="https://drive.google.com/drive/folders/abc",
            protocol_number="1653213/2026",
        ),
    ]
    resolve_sac_mock.return_value = SacFolderContext(
        consumer_folder_id="folder-consumer",
        sac_folder_id="folder-sac",
        complaint_pdf=DriveFileInfo(
            "pdf-1",
            "Atendimento Procon - MARIA.pdf",
            "application/pdf",
            None,
        ),
        summary_txt=None,
        supporting_files=[],
    )
    find_existing_mock.return_value = ExistingResponseOutputs(
        full_response_url="https://drive/full",
        summary_response_url="https://drive/summary",
        unified_pdf_url="https://drive/unified",
    )

    results = elaborate_pending_responses(
        ResponsePipelineOptions(
            work_dir=tmp_path / "work",
            state_path=tmp_path / "state.json",
            monday_api_token="token-test",
            gemini_api_key="gemini-test",
        ),
    )

    assert len(results) == 1
    assert results[0].status == "skipped_duplicate"
    generate_mock.assert_not_called()
    update_monday_mock.assert_called_once()
