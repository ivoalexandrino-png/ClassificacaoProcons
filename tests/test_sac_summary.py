"""Testes de montagem do resumo SAC a partir da pasta Informações."""

from pathlib import Path
from unittest.mock import patch

import pytest

from classificacao_procons.drive.client import DriveClientError
from classificacao_procons.drive.reader import DriveFileInfo, SacFolderContext
from classificacao_procons.drive.sac_summary import (
    build_sac_summary_from_drive_files,
    collect_sac_material_files,
    extract_local_file_text,
)


def _context_without_txt() -> SacFolderContext:
    return SacFolderContext(
        consumer_folder_id="consumer",
        sac_folder_id="sac",
        complaint_pdf=DriveFileInfo(
            "cip",
            "Reclamacao.pdf",
            "application/pdf",
            None,
        ),
        summary_txt=None,
        supporting_files=[
            DriveFileInfo("a", "Cancelado.pdf", "application/pdf", None),
            DriveFileInfo("b", "Tratativa zendesk.pdf", "application/pdf", None),
            DriveFileInfo("c", "image.png", "image/png", None),
        ],
    )


class TestCollectSacMaterialFiles:
    def test_should_include_all_supporting_files_when_no_txt(self) -> None:
        files = collect_sac_material_files(_context_without_txt())
        assert len(files) == 3
        assert files[0].name.endswith(".pdf")


class TestExtractLocalFileText:
    def test_should_read_txt_file(self, tmp_path: Path) -> None:
        path = tmp_path / "resumo.txt"
        path.write_text("Assinatura cancelada em 10/07.", encoding="utf-8")
        assert "cancelada" in extract_local_file_text(path)


class TestBuildSacSummaryFromDriveFiles:
    def test_should_raise_when_folder_empty(self) -> None:
        with pytest.raises(DriveClientError, match="sem arquivos"):
            build_sac_summary_from_drive_files(files=(), work_dir=Path("/tmp/x"))

    @patch("classificacao_procons.drive.sac_summary.download_drive_file")
    def test_should_concatenate_pdf_texts(self, download_mock, tmp_path: Path) -> None:
        def fake_download(*, file_id: str, destination: Path, token_path=None):
            destination.parent.mkdir(parents=True, exist_ok=True)
            if file_id == "a":
                destination.write_text("Texto cancelamento", encoding="utf-8")
            else:
                destination.write_text("Texto chargeback", encoding="utf-8")
            return destination

        download_mock.side_effect = fake_download

        with patch(
            "classificacao_procons.drive.sac_summary.extract_local_file_text",
            side_effect=lambda path: path.read_text(encoding="utf-8"),
        ):
            summary = build_sac_summary_from_drive_files(
                files=(
                    DriveFileInfo("a", "Cancelado.pdf", "application/pdf", None),
                    DriveFileInfo("b", "Chargeback.pdf", "application/pdf", None),
                ),
                work_dir=tmp_path / "sac",
            )

        assert "Cancelado.pdf" in summary
        assert "cancelamento" in summary
        assert "chargeback" in summary

    @patch("classificacao_procons.drive.sac_summary.download_drive_file")
    @patch(
        "classificacao_procons.llm.document_vision.gemini_extract_text_from_document",
    )
    def test_should_use_gemini_when_sac_pdf_has_no_text_layer(
        self,
        vision_mock,
        download_mock,
        tmp_path: Path,
    ) -> None:
        def fake_download(*, file_id: str, destination: Path, token_path=None):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"%PDF-1.4")
            return destination

        download_mock.side_effect = fake_download
        vision_mock.return_value = "Histórico Zendesk transcrito."

        summary = build_sac_summary_from_drive_files(
            files=(DriveFileInfo("a", "Tratativa.pdf", "application/pdf", None),),
            work_dir=tmp_path / "sac",
            gemini_api_key="gemini-key",
        )

        assert "Zendesk" in summary
        vision_mock.assert_called_once()

