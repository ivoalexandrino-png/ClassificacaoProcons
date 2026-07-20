"""Testes de integração ALERJ no pipeline."""

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from classificacao_procons.drive.client import DriveUploadResult
from classificacao_procons.models import ProconComplaint, ProconNotificationEmail
from classificacao_procons.monday.client import MondayRegistrationResult
from classificacao_procons.pipeline import PipelineOptions, process_new_complaints


def _alerj_notification() -> ProconNotificationEmail:
    return ProconNotificationEmail(
        message_id="msg-alerj",
        subject="Fwd: NOTIFICAÇÃO N.º 245984/2026",
        sender="vanessa.barajas@b4a.com.br",
        received_at=datetime(2026, 3, 16, 13, 25),
        portal_url="",
        source_id="alerj",
        protocol_number="312133/2026",
        state="RJ",
    )


def _complaint(pdf_path: Path) -> ProconComplaint:
    return ProconComplaint(
        access_code="312133/2026",
        consumer_name="Manuela Cadilhe Duarte",
        consumer_cpf="13593852748",
        cip_fa_number="312133/2026",
        complaint_date=date(2026, 3, 12),
        response_deadline=None,
        cause="Cobrança integral indevida na renovação do plano anual",
        state="RJ",
        pdf_path=str(pdf_path),
    )


@patch("classificacao_procons.pipeline.GmailProconFetcher")
@patch("classificacao_procons.pipeline.has_gmail_modify_access", return_value=True)
@patch("classificacao_procons.pipeline.has_valid_token", return_value=True)
@patch("classificacao_procons.pipeline.register_complaint")
@patch("classificacao_procons.pipeline.parse_alerj_pdf")
@patch("classificacao_procons.pipeline.download_alerj_pdf_attachment")
@patch("classificacao_procons.pipeline.save_complaint_pdf")
def test_should_process_alerj_notification(
    save_pdf_mock,
    download_pdf_mock,
    parse_pdf_mock,
    register_monday_mock,
    _has_token_mock,
    _modify_mock,
    fetcher_cls_mock,
    tmp_path,
) -> None:
    pdf_path = tmp_path / "alerj-312133-2026.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    fetcher = MagicMock()
    fetcher._service = MagicMock()
    fetcher_cls_mock.from_credentials.return_value = fetcher
    fetcher.list_unread_notifications.return_value = [_alerj_notification()]
    fetcher.fetch_message_payload.return_value = {"parts": []}
    download_pdf_mock.return_value = pdf_path
    parse_pdf_mock.return_value = _complaint(pdf_path)
    save_pdf_mock.return_value = DriveUploadResult(
        consumer_folder_id="folder-1",
        consumer_folder_url="https://drive.google.com/folder/folder-1",
        pdf_file_id="file-1",
        pdf_url="https://drive.google.com/file/file-1/view",
    )
    register_monday_mock.return_value = MondayRegistrationResult(
        item_id="monday-1",
        board_id="board-1",
        item_url="https://b4a.monday.com/boards/board-1/pulses/monday-1",
    )

    results = process_new_complaints(
        PipelineOptions(
            download_dir=tmp_path / "downloads",
            state_path=tmp_path / "processed.json",
            monday_api_token="token-test",
        ),
    )

    assert len(results) == 1
    assert results[0].status == "success"
    assert results[0].state == "RJ"
    assert results[0].protocol_number == "312133/2026"
    assert results[0].consumer_name == "Manuela Cadilhe Duarte"
    assert results[0].sac_deadline == date(2026, 3, 21)
    assert results[0].legal_deadline == date(2026, 3, 22)
    assert results[0].procon_response_deadline == date(2026, 3, 26)
    download_pdf_mock.assert_called_once()
    parse_pdf_mock.assert_called_once_with(pdf_path)
    register_monday_mock.assert_called_once()
