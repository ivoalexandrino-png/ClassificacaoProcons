"""Testes de extração de texto de PDF."""

from pathlib import Path

import pytest

from classificacao_procons.gemini.client import GeminiClientError
from classificacao_procons.llm.pdf_text import extract_pdf_text


def test_should_raise_when_pdf_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(GeminiClientError, match="não encontrado"):
        extract_pdf_text(tmp_path / "missing.pdf")
