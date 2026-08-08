"""Extração de texto de PDFs locais (pypdf + Gemini quando necessário)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from classificacao_procons.drive.sac_summary import (
    _vision_extract_local_file_text,
    extract_local_file_text,
)

_MIN_TEXT_CHARS_FOR_OCR_SKIP = 40


@dataclass(frozen=True)
class ExtractedDocumentText:
    text: str
    method: str


def extract_pdf_text(
    path: Path,
    *,
    gemini_api_key: str | None,
    allow_vision: bool,
) -> ExtractedDocumentText:
    body = extract_local_file_text(path)
    if len(body.strip()) >= _MIN_TEXT_CHARS_FOR_OCR_SKIP:
        return ExtractedDocumentText(text=body, method="pypdf")
    if allow_vision and gemini_api_key:
        vision_text = _vision_extract_local_file_text(path, gemini_api_key=gemini_api_key)
        if vision_text.strip():
            return ExtractedDocumentText(text=vision_text, method="gemini_vision")
    return ExtractedDocumentText(text=body, method="pypdf")
