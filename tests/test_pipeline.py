"""Testes do pipeline automático."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from classificacao_procons.drive.client import DriveUploadResult
from classificacao_procons.models import ProconComplaint, ProconNotificationEmail
from classificacao_procons.monday.client import MondayRegistrationResult
from classificacao_procons.pipeline import (
    PipelineOptions,
    calculate_sac_and_legal_deadlines,
    process_new_complaints,
)


def _notification() -> ProconNotificationEmail:
    return ProconNotificationEmail(
        message_id="msg-1",
        subject="Fundação Procon-SP - Notificação de emissão de CIP",
        sender="procon.naoresponder@procon.sp.gov.br",
        received_at=datetime(2026, 7, 14, 10, 0),
        portal_url="https://fornecedor2.procon.sp.gov.br/login",
        access_code="CODE-123",
        protocol_number="1653213/2026",
    )


def _complaint() -> ProconComplaint:
    return ProconComplaint(
        access_code="CODE-123",
        consumer_name="MARIA SILVA",
        consumer_cpf="12345678901",
        cip_fa_number="1653213/2026",
        complaint_date=date(2026, 7, 14),
        response_deadline=date(2026, 7, 24),
        cause="Atraso na entrega",
        pdf_path="downloads/test.pdf",
    )


class TestCalculateDeadlines:
    def test_should_calculate_sac_and_legal_deadlines(self) -> None:
        sac, legal = calculate_sac_and_legal_deadlines(base_date=date(2026, 7, 14))
        assert sac == date(2026, 7, 19)
        assert legal == date(2026, 7, 20)


@patch("classificacao_procons.pipeline.GmailProconFetcher")
@patch("classificacao_procons.pipeline.has_gmail_modify_access", return_value=True)
@patch("classificacao_procons.pipeline.has_valid_token", return_value=True)
@patch("classificacao_procons.pipeline.register_complaint")
@patch("classificacao_procons.pipeline.fetch_complaint")
@patch("classificacao_procons.pipeline.save_complaint_pdf")
def test_should_process_notification_end_to_end(
    save_pdf_mock,
    fetch_complaint_mock,
    register_monday_mock,
    _has_token_mock,
    _modify_mock,
    fetcher_cls_mock,
    tmp_path,
) -> None:
    fetcher = MagicMock()
    fetcher_cls_mock.from_credentials.return_value = fetcher
    fetcher.list_unread_notifications.return_value = [_notification()]
    fetch_complaint_mock.return_value = _complaint()
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

    options = PipelineOptions(
        download_dir=tmp_path / "downloads",
        state_path=tmp_path / "processed.json",
        mark_read=True,
        monday_api_token="token-test",
    )
    results = process_new_complaints(options)

    assert len(results) == 1
    assert results[0].status == "success"
    assert results[0].consumer_name == "MARIA SILVA"
    assert results[0].pdf_url == "https://drive.google.com/file/file-1/view"
    assert results[0].monday_item_url == "https://b4a.monday.com/boards/board-1/pulses/monday-1"
    fetcher.mark_as_read.assert_called_once_with("msg-1")
    register_monday_mock.assert_called_once()


@patch("classificacao_procons.pipeline.GmailProconFetcher")
@patch("classificacao_procons.pipeline.has_valid_token", return_value=True)
def test_should_dry_run_without_portal_or_drive(
    _has_token_mock,
    fetcher_cls_mock,
) -> None:
    fetcher = MagicMock()
    fetcher_cls_mock.from_credentials.return_value = fetcher
    fetcher.list_unread_notifications.return_value = [_notification()]

    results = process_new_complaints(PipelineOptions(dry_run=True))

    assert results[0].status == "dry_run"
    assert results[0].protocol_number == "1653213/2026"
