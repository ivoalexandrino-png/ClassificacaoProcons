"""Testes de integração Uberlândia no pipeline."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from classificacao_procons.drive.client import DriveUploadResult
from classificacao_procons.models import ProconComplaint, ProconNotificationEmail
from classificacao_procons.monday.client import MondayRegistrationResult
from classificacao_procons.pipeline import PipelineOptions, process_new_complaints


def _uberlandia_notification() -> ProconNotificationEmail:
    return ProconNotificationEmail(
        message_id="msg-uber",
        subject="Notificação",
        sender="faleprocon@uberlandia.mg.gov.br",
        received_at=datetime(2026, 7, 20, 11, 0),
        portal_url="https://faleprocon.uberlandia.mg.gov.br/empresas",
        source_id="uberlandia",
        protocol_number="2026.02.0399.008.51708",
        state="MG",
        consumer_name="Danielle cardoso van eyken",
        consumer_cpf="04408548650",
        complaint_date=date(2026, 3, 6),
        cause="Renovação automática sem consentimento",
    )


def _complaint() -> ProconComplaint:
    return ProconComplaint(
        access_code="2026.02.0399.008.51708",
        consumer_name="Danielle cardoso van eyken",
        consumer_cpf="04408548650",
        cip_fa_number="2026.02.0399.008.51708",
        complaint_date=date(2026, 3, 6),
        response_deadline=None,
        cause="Renovação automática sem consentimento",
        state="MG",
        pdf_path="downloads/uberlandia-test.pdf",
    )


@patch("classificacao_procons.pipeline.GmailProconFetcher")
@patch("classificacao_procons.pipeline.has_gmail_modify_access", return_value=True)
@patch("classificacao_procons.pipeline.has_valid_token", return_value=True)
@patch("classificacao_procons.pipeline.register_complaint")
@patch("classificacao_procons.pipeline.fetch_uberlandia_complaint")
@patch("classificacao_procons.pipeline.resolve_portal_credentials")
@patch("classificacao_procons.pipeline.save_complaint_pdf")
def test_should_process_uberlandia_notification(
    save_pdf_mock,
    resolve_credentials_mock,
    fetch_uberlandia_mock,
    register_monday_mock,
    _has_token_mock,
    _modify_mock,
    fetcher_cls_mock,
    tmp_path,
) -> None:
    fetcher = MagicMock()
    fetcher_cls_mock.from_credentials.return_value = fetcher
    fetcher.list_unread_notifications.return_value = [_uberlandia_notification()]
    resolve_credentials_mock.return_value = MagicMock(login="user", password="pass")
    fetch_uberlandia_mock.return_value = _complaint()
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
    assert results[0].state == "MG"
    assert results[0].protocol_number == "2026.02.0399.008.51708"
    assert results[0].sac_deadline == date(2026, 7, 25)
    assert results[0].legal_deadline == date(2026, 7, 26)
    resolve_credentials_mock.assert_called_once_with("uberlandia", api_token="token-test")
    fetch_uberlandia_mock.assert_called_once()
    register_monday_mock.assert_called_once()
