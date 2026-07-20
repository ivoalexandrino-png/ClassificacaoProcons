"""Testes do gerador de PDF unificado."""

from pathlib import Path
from unittest.mock import patch

import pytest

from classificacao_procons.drive.pdf_builder import (
    build_unified_response_pdf,
    is_mergeable_supporting_file,
    local_supporting_file_name,
    merge_pdf_files,
    text_to_pdf,
)
from classificacao_procons.drive.reader import DriveFileInfo


class TestMergeableSupportingFile:
    def test_should_accept_pdf_and_images(self) -> None:
        assert is_mergeable_supporting_file(
            DriveFileInfo("1", "nota.pdf", "application/pdf", None),
        )
        assert is_mergeable_supporting_file(
            DriveFileInfo("2", "foto.png", "image/png", None),
        )

    def test_should_reject_txt_files(self) -> None:
        assert not is_mergeable_supporting_file(
            DriveFileInfo("3", "informacoes.txt", "text/plain", None),
        )

    def test_should_add_pdf_extension_for_extensionless_drive_pdf(self) -> None:
        file_info = DriveFileInfo("4", "Conta conectada", "application/pdf", None)
        assert local_supporting_file_name(file_info) == "Conta conectada.pdf"
        assert is_mergeable_supporting_file(file_info)


class TestPdfBuilder:
    def test_should_create_text_pdf(self, tmp_path: Path) -> None:
        destination = tmp_path / "resposta.pdf"
        text_to_pdf(text="Resposta formal ao Procon.", destination=destination, title="Título")
        assert destination.exists()
        assert destination.stat().st_size > 0

    def test_should_merge_existing_pdfs(self, tmp_path: Path) -> None:
        first = tmp_path / "a.pdf"
        second = tmp_path / "b.pdf"
        text_to_pdf(text="Parte A", destination=first, title="A")
        text_to_pdf(text="Parte B", destination=second, title="B")
        output = tmp_path / "merged.pdf"
        merge_pdf_files(sources=[first, second], destination=output)
        assert output.exists()
        assert output.stat().st_size > first.stat().st_size

    @patch("classificacao_procons.drive.pdf_builder.image_to_pdf")
    def test_should_build_unified_pdf_with_response_complaint_and_attachments(
        self,
        image_to_pdf_mock,
        tmp_path: Path,
    ) -> None:
        complaint = tmp_path / "reclamacao.pdf"
        text_to_pdf(text="Reclamação", destination=complaint, title="Reclamação")
        attachment = tmp_path / "anexo.pdf"
        text_to_pdf(text="Anexo SAC", destination=attachment, title="Anexo")

        def fake_image_to_pdf(*, image_path: Path, destination: Path) -> Path:
            text_to_pdf(text="Imagem", destination=destination, title="Imagem")
            return destination

        image_to_pdf_mock.side_effect = fake_image_to_pdf
        output = tmp_path / "unificado.pdf"
        build_unified_response_pdf(
            response_text="Resposta completa ao Procon.",
            complaint_pdf=complaint,
            supporting_files=[attachment],
            destination=output,
        )
        assert output.exists()

    def test_should_skip_unrecognized_supporting_file_in_unified_pdf(
        self,
        tmp_path: Path,
    ) -> None:
        complaint = tmp_path / "reclamacao.pdf"
        text_to_pdf(text="Reclamação", destination=complaint, title="Reclamação")
        unknown = tmp_path / "planilha.bin"
        unknown.write_bytes(b"not-a-pdf")
        output = tmp_path / "unificado.pdf"
        build_unified_response_pdf(
            response_text="Resposta completa ao Procon.",
            complaint_pdf=complaint,
            supporting_files=[unknown],
            destination=output,
        )
        assert output.exists()

    def test_should_raise_when_unified_pdf_exceeds_limit(self, tmp_path: Path) -> None:
        first = tmp_path / "big.pdf"
        second = tmp_path / "also.pdf"
        output = tmp_path / "out.pdf"
        text_to_pdf(text="A", destination=first, title="A")
        text_to_pdf(text="B", destination=second, title="B")
        with patch(
            "classificacao_procons.drive.pdf_builder.MAX_UNIFIED_PDF_BYTES",
            10,
        ):
            with pytest.raises(Exception, match="9MB"):
                merge_pdf_files(sources=[first, second], destination=output)
