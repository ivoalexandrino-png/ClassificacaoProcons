"""Testes de leitura do Drive."""

from datetime import datetime

from classificacao_procons.drive.reader import (
    RESPONSE_OUTPUT_FOLDER,
    DriveFileInfo,
    _find_complaint_pdf,
    _find_summary_txt,
    _score_sac_folder_name,
    _select_sac_subfolder,
    extract_drive_resource_id,
    is_procon_complaint_pdf,
)


class TestDriveReaderHelpers:
    def test_should_extract_folder_id_from_drive_url(self) -> None:
        url = "https://drive.google.com/drive/folders/abc123XYZ"
        assert extract_drive_resource_id(url) == "abc123XYZ"

    def test_should_prefer_informacoes_subfolder(self) -> None:
        folders = [
            DriveFileInfo(
                "1",
                "Outros",
                "application/vnd.google-apps.folder",
                datetime(2026, 7, 10),
            ),
            DriveFileInfo(
                "2",
                "Informações",
                "application/vnd.google-apps.folder",
                datetime(2026, 7, 9),
            ),
        ]
        selected = _select_sac_subfolder(folders)
        assert selected is not None
        assert selected.file_id == "2"

    def test_should_ignore_resposta_automatica_subfolder(self) -> None:
        folders = [
            DriveFileInfo(
                "1",
                RESPONSE_OUTPUT_FOLDER,
                "application/vnd.google-apps.folder",
                datetime(2026, 8, 20),
            ),
            DriveFileInfo(
                "2",
                "Informações",
                "application/vnd.google-apps.folder",
                datetime(2026, 8, 15),
            ),
        ]
        selected = _select_sac_subfolder(folders)
        assert selected is not None
        assert selected.file_id == "2"

    def test_should_score_sac_folder_names(self) -> None:
        assert _score_sac_folder_name("Informações") > _score_sac_folder_name("Outros")

    def test_should_find_complaint_pdf_by_prefix(self) -> None:
        files = [
            DriveFileInfo("1", "Atendimento Procon - MARIA - 123.pdf", "application/pdf", None),
            DriveFileInfo("2", "outro.pdf", "application/pdf", None),
        ]
        found = _find_complaint_pdf(files)
        assert found is not None
        assert found.file_id == "1"

    def test_should_flag_procon_complaint_pdf_for_exclusion_from_unified(self) -> None:
        procon = DriveFileInfo(
            "1",
            "Atendimento Procon - ANA - 1668179.pdf",
            "application/pdf",
            None,
        )
        other = DriveFileInfo("2", "comprovante-estorno.pdf", "application/pdf", None)
        assert is_procon_complaint_pdf(procon)
        assert not is_procon_complaint_pdf(other)

    def test_should_find_summary_txt(self) -> None:
        files = [
            DriveFileInfo("1", "informacoes.txt", "text/plain", None),
            DriveFileInfo("2", "print.pdf", "application/pdf", None),
        ]
        found = _find_summary_txt(files)
        assert found is not None
        assert found.name == "informacoes.txt"
