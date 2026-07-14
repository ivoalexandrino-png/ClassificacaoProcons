"""Testes do cliente Google Drive."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from classificacao_procons.drive.client import (
    DriveClientError,
    _sanitize_folder_name,
    ensure_consumer_folder,
    save_complaint_pdf,
    upload_pdf_to_folder,
)


class TestSanitizeFolderName:
    def test_should_trim_and_normalize_whitespace(self) -> None:
        assert _sanitize_folder_name("  MARIA   SILVA  ") == "MARIA SILVA"

    def test_should_raise_when_name_is_empty(self) -> None:
        with pytest.raises(DriveClientError, match="Nome da consumidora vazio"):
            _sanitize_folder_name("   ")


class TestDriveOperations:
    def test_should_reuse_existing_consumer_folder(self) -> None:
        service = MagicMock()
        service.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "folder-123"}],
        }
        service.files.return_value.get.return_value.execute.return_value = {
            "webViewLink": "https://drive.google.com/folder/folder-123",
        }

        folder_id, folder_url = ensure_consumer_folder(
            service,
            parent_folder_id="parent-abc",
            consumer_name="JANIS LEAO",
        )

        assert folder_id == "folder-123"
        assert folder_url == "https://drive.google.com/folder/folder-123"
        service.files.return_value.create.assert_not_called()

    def test_should_upload_pdf_to_folder(self, tmp_path: Path) -> None:
        pdf = tmp_path / "reclamacao.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")

        service = MagicMock()
        service.files.return_value.create.return_value.execute.return_value = {
            "id": "file-999",
            "webViewLink": "https://drive.google.com/file/file-999/view",
        }

        file_id, file_url = upload_pdf_to_folder(
            service,
            folder_id="folder-123",
            pdf_path=pdf,
        )

        assert file_id == "file-999"
        assert "file-999" in file_url

    @patch("classificacao_procons.drive.client._build_drive_service")
    def test_should_save_complaint_pdf_end_to_end(self, build_service_mock, tmp_path: Path) -> None:
        pdf = tmp_path / "procon.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")

        service = MagicMock()
        build_service_mock.return_value = service

        list_mock = service.files.return_value.list.return_value.execute
        list_mock.return_value = {"files": []}

        create_mock = service.files.return_value.create.return_value.execute
        create_mock.side_effect = [
            {"id": "folder-new", "webViewLink": "https://drive.google.com/folder/folder-new"},
            {"id": "file-new", "webViewLink": "https://drive.google.com/file/file-new/view"},
        ]
        service.files.return_value.get.return_value.execute.return_value = {
            "webViewLink": "https://drive.google.com/folder/folder-new",
        }

        result = save_complaint_pdf(consumer_name="JANIS LEAO", pdf_path=pdf)

        assert result.pdf_file_id == "file-new"
        assert result.consumer_folder_id == "folder-new"
