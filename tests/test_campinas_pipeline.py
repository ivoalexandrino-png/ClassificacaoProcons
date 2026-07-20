"""Testes de integração Campinas no pipeline."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from classificacao_procons.drive.client import DriveUploadResult
from classificacao_procons.models import ProconComplaint, ProconNotificationEmail
from classificacao_procons.monday.client import MondayRegistrationResult
from classificacao_procons.pipeline import PipelineOptions, process_new_complaints


def _campinas_notification() -> ProconNotificationEmail:
    return ProconNotificationEmail(
        message_id="msg-campinas",
        subject="Notificação CIP",
        sender="procon.adm@campinas.sp.gov.br",
        received_at=datetime(2026, 7, 10, 9, 0),
        portal_url="https://procon.campinas.sp.gov.br/",
        source_id="campinas",
        protocol_number="12345/2026",
        state="Campinas",
        consumer_name="MARIA DA SILVA",
        consumer_cpf="12345678901",
        complaint_date=date(2026, 7, 10),
    )


def _complaint() -> ProconComplaint:
    return ProconComplaint(
        access_code="12345/2026",
        consumer_name="MARIA DA SILVA",
        consumer_cpf="12345678901",
        cip_fa_number="12345/2026",
        complaint_date=date(2026, 7, 10),
        response_deadline=date(2026, 7, 20),
        cause="Produto com defeito",
        state="Campinas",
        pdf_path="downloads/campinas-12345-2026.pdf",
    )


@patch("classificacao_procons.pipeline.GmailProconFetcher")
@patch("classificacao_procons.pipeline.has_gmail_modify_access", return_value=True)
@patch("classificacao_procons.pipeline.has_valid_token", return_value=True)
@patch("classificacao_procons.pipeline.register_complaint")
@patch("classificacao_procons.pipeline.fetch_campinas_complaint")
@patch("classificacao_procons.pipeline.resolve_portal_credentials")
@patch("classificacao_procons.pipeline.save_complaint_pdf")
def test_should_process_campinas_notification(
    save_pdf_mock,
    resolve_credentials_mock,
    fetch_campinas_mock,
    register_monday_mock,
    _has_token_mock,
    _modify_mock,
    fetcher_cls_mock,
    tmp_path,
) -> None:
    fetcher = MagicMock()
    fetcher_cls_mock.from_credentials.return_value = fetcher
    fetcher.list_unread_notifications.return_value = [_campinas_notification()]
    resolve_credentials_mock.return_value = MagicMock(login="user", password="pass")
    fetch_campinas_mock.return_value = _complaint()
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
    assert results[0].state == "Campinas"
    assert results[0].protocol_number == "12345/2026"
    assert results[0].sac_deadline == date(2026, 7, 13)
    assert results[0].legal_deadline == date(2026, 7, 14)
    resolve_credentials_mock.assert_called_once_with("campinas", api_token="token-test")
    fetch_campinas_mock.assert_called_once()
    portal_options = fetch_campinas_mock.call_args.args[0]
    assert portal_options.consumer_name_hint == "MARIA DA SILVA"
    assert portal_options.consumer_cpf_hint == "12345678901"
    register_monday_mock.assert_called_once()
