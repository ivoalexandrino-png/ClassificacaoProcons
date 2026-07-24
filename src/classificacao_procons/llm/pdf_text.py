"""Extração de texto de PDF para provedores sem suporte nativo a anexo."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from classificacao_procons.gemini.client import GeminiClientError

DEFAULT_MAX_PDF_CHARS = 120_000


def extract_pdf_text(pdf_path: Path, *, max_chars: int = DEFAULT_MAX_PDF_CHARS) -> str:
    """Extrai texto do PDF da reclamação para prompts baseados em texto."""
    if not pdf_path.exists():
        raise GeminiClientError(f"PDF da reclamação não encontrado: {pdf_path}")

    try:
        reader = PdfReader(str(pdf_path))
    except Exception as exc:
        raise GeminiClientError(f"Falha ao ler PDF da reclamação: {exc}") from exc

    parts: list[str] = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            parts.append(page_text)

    full_text = "\n".join(parts).strip()
    if not full_text:
        raise GeminiClientError(
            "Não foi possível extrair texto do PDF da reclamação (PDF pode ser só imagem).",
        )

    if len(full_text) > max_chars:
        return full_text[:max_chars].rstrip()
    return full_text
