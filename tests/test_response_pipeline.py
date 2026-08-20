"""Testes do pipeline de elaboração de resposta."""

import json
from unittest.mock import patch

from classificacao_procons.drive.reader import (
    DriveFileInfo,
    ExistingResponseOutputs,
    SacFolderContext,
)
from classificacao_procons.gemini.client import GeminiQuotaError, GeneratedResponse
from classificacao_procons.models import MondayCaseReady
from classificacao_procons.response_pipeline import (
    ResponsePipelineOptions,
    elaborate_pending_responses,
)


def _case_ready() -> MondayCaseReady:
    return MondayCaseReady(
        item_id="100",
        item_name="MARIA SILVA",
        docs_sac_url="https://drive.google.com/drive/folders/abc",
        protocol_number="1653213/2026",
    )


def _sac_context() -> SacFolderContext:
    return SacFolderContext(
        consumer_folder_id="folder-consumer",
        sac_folder_id="folder-sac",
        complaint_pdf=DriveFileInfo("pdf-1", "Atendimento.pdf", "application/pdf", None),
        summary_txt=DriveFileInfo("txt-1", "informacoes.txt", "text/plain", None),
        supporting_files=[],
    )


def _fake_download(*, file_id: str, destination, token_path=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if file_id == "txt-1":
        destination.write_text("Cliente recebeu o produto.", encoding="utf-8")
    else:
        destination.write_bytes(b"%PDF-1.4")
    return destination


@patch("classificacao_procons.drive.sac_summary.download_drive_file")
@patch("classificacao_procons.response_pipeline.find_existing_response_outputs", return_value=None)
@patch("classificacao_procons.response_pipeline.generate_procon_response")
@patch("classificacao_procons.response_pipeline.download_drive_file")
@patch("classificacao_procons.response_pipeline.resolve_sac_folder_context")
@patch("classificacao_procons.response_pipeline.list_cases_ready_for_elaboration")
@patch("classificacao_procons.response_pipeline.has_valid_token", return_value=True)
def test_should_defer_case_when_gemini_quota_exhausted(
    _token_mock,
    list_cases_mock,
    resolve_sac_mock,
    download_mock,
    generate_mock,
    _find_existing_mock,
    download_sac_mock,
    tmp_path,
) -> None:
    """Cota do Gemini esgotada: caso adiado (não erro) e não marcado processado."""
    list_cases_mock.return_value = [_case_ready()]
    resolve_sac_mock.return_value = _sac_context()
    download_mock.side_effect = _fake_download
    download_sac_mock.side_effect = _fake_download
    generate_mock.side_effect = GeminiQuotaError("Limite gratuito do Gemini esgotado.")

    state_path = tmp_path / "state.json"
    options = ResponsePipelineOptions(
        work_dir=tmp_path / "work",
        state_path=state_path,
        monday_api_token="token-test",
        gemini_api_key="gemini-test",
    )
    results = elaborate_pending_responses(options)

    assert len(results) == 1
    assert results[0].status == "deferred_quota"
    if state_path.exists():
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        assert "100" not in saved.get("item_ids", [])


@patch("classificacao_procons.drive.sac_summary.download_drive_file")
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
    download_sac_mock,
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
    download_sac_mock.side_effect = fake_download
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
    assert results[0].status == "skipped_existing"
    generate_mock.assert_not_called()
    update_monday_mock.assert_called_once()


@patch(
    "classificacao_procons.response_pipeline.clear_automatic_response_output_files",
    return_value=0,
)
@patch("classificacao_procons.drive.sac_summary.download_drive_file")
@patch("classificacao_procons.response_pipeline.update_elaborated_response_links")
@patch("classificacao_procons.response_pipeline.upload_pdf_file", return_value="https://drive/unified")
@patch("classificacao_procons.response_pipeline.upload_text_file", return_value="https://drive/text")
@patch("classificacao_procons.response_pipeline.ensure_output_folder", return_value="out-folder")
@patch("classificacao_procons.response_pipeline.build_unified_response_pdf")
@patch("classificacao_procons.response_pipeline.generate_procon_response")
@patch("classificacao_procons.response_pipeline.find_existing_response_outputs")
@patch("classificacao_procons.response_pipeline.download_drive_file")
@patch("classificacao_procons.response_pipeline.resolve_sac_folder_context")
@patch("classificacao_procons.response_pipeline.load_cases_for_elaboration_by_item_ids")
@patch("classificacao_procons.response_pipeline.has_valid_token", return_value=True)
def test_should_regenerate_when_force_reelaborate(
    _token_mock,
    load_by_id_mock,
    resolve_sac_mock,
    download_mock,
    find_existing_mock,
    generate_mock,
    _build_pdf_mock,
    _ensure_folder_mock,
    _upload_text_mock,
    _upload_pdf_mock,
    update_monday_mock,
    download_sac_mock,
    clear_outputs_mock,
    tmp_path,
) -> None:
    load_by_id_mock.return_value = [_case_ready()]
    resolve_sac_mock.return_value = _sac_context()
    download_mock.side_effect = _fake_download
    download_sac_mock.side_effect = _fake_download
    find_existing_mock.return_value = ExistingResponseOutputs(
        full_response_url="https://drive/old-full",
        summary_response_url="https://drive/old-summary",
        unified_pdf_url="https://drive/old-unified",
    )
    generate_mock.return_value = GeneratedResponse(
        analysis="Análise.",
        draft="Rascunho.",
        final_response="Resposta alinhada ao SAC.",
        portal_summary="Resumo.",
    )

    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"monday_item_ids": ["100"]}, ensure_ascii=False),
        encoding="utf-8",
    )

    results = elaborate_pending_responses(
        ResponsePipelineOptions(
            work_dir=tmp_path / "work",
            state_path=state_path,
            monday_api_token="token-test",
            gemini_api_key="gemini-test",
            monday_item_ids=frozenset({"100"}),
            force_reelaborate=True,
        ),
    )

    assert len(results) == 1
    assert results[0].status == "success"
    find_existing_mock.assert_not_called()
    clear_outputs_mock.assert_called_once()
    generate_mock.assert_called_once()
    update_monday_mock.assert_called_once()


@patch("classificacao_procons.response_pipeline.list_cases_with_elaborated_responses")
@patch("classificacao_procons.response_pipeline.has_valid_token", return_value=True)
def test_should_use_existing_list_when_reelaborate_existing_dry_run(
    _token_mock,
    list_existing_mock,
    tmp_path,
) -> None:
    list_existing_mock.return_value = [_case_ready()]

    results = elaborate_pending_responses(
        ResponsePipelineOptions(
            work_dir=tmp_path / "work",
            state_path=tmp_path / "state.json",
            monday_api_token="token-test",
            reelaborate_existing=True,
            force_reelaborate=True,
            dry_run=True,
        ),
    )

    assert len(results) == 1
    assert results[0].status == "dry_run"
    list_existing_mock.assert_called_once()


@patch("classificacao_procons.response_pipeline.create_item_update")
@patch("classificacao_procons.response_pipeline.resolve_sac_folder_context")
@patch("classificacao_procons.response_pipeline.list_cases_ready_for_elaboration")
@patch("classificacao_procons.response_pipeline.has_valid_token", return_value=True)
def test_should_post_monday_update_when_docs_sac_protocol_mismatches(
    _token_mock,
    list_cases_mock,
    resolve_sac_mock,
    create_update_mock,
    tmp_path,
) -> None:
    from classificacao_procons.drive.client import DriveClientError
    from classificacao_procons.drive.protocol import build_protocol_mismatch_error

    list_cases_mock.return_value = [_case_ready()]
    resolve_sac_mock.side_effect = DriveClientError(
        build_protocol_mismatch_error(
            expected_protocol="1759897/2026",
            found_protocol="1656146/2026",
            pdf_name="Atendimento Procon - GABRIELE - 1656146-2026 - 15-07-2026.pdf",
        ),
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
    assert results[0].status == "error"
    assert "Pasta Docs SAC inconsistente" in (results[0].error or "")
    create_update_mock.assert_called_once()
    assert create_update_mock.call_args.kwargs["item_id"] == "100"
