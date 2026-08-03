"""Testes de extração multimodal via Gemini."""

from pathlib import Path
from unittest.mock import patch

import pytest

from classificacao_procons.gemini.client import GeminiClientError
from classificacao_procons.llm.document_vision import gemini_extract_text_from_document


def test_should_raise_when_file_missing(tmp_path: Path) -> None:
    with pytest.raises(GeminiClientError, match="não encontrado"):
        gemini_extract_text_from_document(
            tmp_path / "doc.pdf",
            api_key="key",
        )


@patch("classificacao_procons.llm.document_vision._gemini_request")
@patch("classificacao_procons.llm.document_vision._resolve_model", return_value="gemini-2.0-flash")
def test_should_extract_text_from_scanned_pdf(
    _model_mock,
    gemini_mock,
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 scanned")
    gemini_mock.return_value = "Texto lido do digitalizado."

    text = gemini_extract_text_from_document(pdf_path, api_key="key")

    assert "digitalizado" in text
    parts = gemini_mock.call_args.kwargs["parts"]
    assert any(part.get("inline_data", {}).get("mime_type") == "application/pdf" for part in parts)


@patch("classificacao_procons.llm.document_vision._gemini_request")
@patch("classificacao_procons.llm.document_vision._resolve_model", return_value="gemini-2.0-flash")
def test_should_extract_text_from_png(
    _model_mock,
    gemini_mock,
    tmp_path: Path,
) -> None:
    png_path = tmp_path / "print.png"
    png_path.write_bytes(b"\x89PNG")
    gemini_mock.return_value = "Conteúdo da captura."

    text = gemini_extract_text_from_document(png_path, api_key="key")

    assert "captura" in text.casefold()
    parts = gemini_mock.call_args.kwargs["parts"]
    assert any(part.get("inline_data", {}).get("mime_type") == "image/png" for part in parts)
