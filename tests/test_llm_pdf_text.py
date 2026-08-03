"""Testes de extração de texto de PDF."""

from pathlib import Path
from unittest.mock import patch

import pytest

from classificacao_procons.gemini.client import GeminiClientError
from classificacao_procons.llm.pdf_text import (
    extract_pdf_text,
    extract_pdf_text_soft,
    resolve_complaint_text,
)


def test_should_raise_when_pdf_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(GeminiClientError, match="não encontrado"):
        extract_pdf_text(tmp_path / "missing.pdf")


def test_should_return_empty_when_pdf_has_no_text_layer(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    assert extract_pdf_text_soft(pdf_path) == ""


@patch("classificacao_procons.llm.document_vision.gemini_extract_text_from_document")
def test_should_fallback_to_gemini_when_pdf_is_scanned(
    vision_mock,
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    vision_mock.return_value = "Texto OCR"

    text = resolve_complaint_text(pdf_path, gemini_api_key="key")

    assert text == "Texto OCR"
    vision_mock.assert_called_once()


def test_should_raise_when_scanned_pdf_and_no_gemini_key(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    with pytest.raises(GeminiClientError, match="só imagem"):
        resolve_complaint_text(pdf_path, gemini_api_key=None)

