"""Extração de texto via Gemini quando pypdf não lê PDF digitalizado / imagem."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from classificacao_procons.gemini.client import (
    GeminiClientError,
    _gemini_request,
    _pdf_part,
    get_model_from_env,
    list_generate_content_models,
    resolve_gemini_model,
)

_EXTRACTION_PROMPT = (
    "Extraia todo o texto legível deste documento (incluindo PDF digitalizado ou imagem). "
    "Preserve parágrafos e listas. Responda somente com o texto extraído, sem comentários."
)

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})
_MAX_EXTRACTED_CHARS = 120_000


def _mime_type_for_path(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in _IMAGE_SUFFIXES:
        mapping = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
        }
        return mapping.get(suffix, "image/jpeg")
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _inline_file_part(path: Path) -> dict[str, object]:
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return _pdf_part(path)
    import base64

    mime = _mime_type_for_path(path)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"inline_data": {"mime_type": mime, "data": encoded}}


def _resolve_model(api_key: str, preferred: str | None) -> str:
    if preferred and preferred.strip():
        return preferred.strip()
    available = list_generate_content_models(api_key=api_key)
    return resolve_gemini_model(
        available_models=available,
        preferred=get_model_from_env(),
    )


def gemini_extract_text_from_document(
    path: Path,
    *,
    api_key: str,
    model: str | None = None,
) -> str:
    """Transcreve documento (PDF digitalizado, imagem, etc.) via Gemini multimodal."""
    if not path.exists():
        raise GeminiClientError(f"Arquivo não encontrado para extração: {path}")

    suffix = path.suffix.casefold()
    if suffix != ".pdf" and suffix not in _IMAGE_SUFFIXES:
        raise GeminiClientError(
            f"Formato não suportado para extração via Gemini: {path.name}",
        )

    selected_model = _resolve_model(api_key, model)
    try:
        raw = _gemini_request(
            api_key=api_key,
            model=selected_model,
            parts=[{"text": _EXTRACTION_PROMPT}, _inline_file_part(path)],
        )
    except GeminiClientError:
        raise
    except OSError as exc:
        raise GeminiClientError(f"Falha ao ler arquivo para extração: {exc}") from exc

    text = raw.strip()
    if not text:
        raise GeminiClientError(
            "Gemini não extraiu texto do documento (arquivo ilegível ou vazio).",
        )
    if len(text) > _MAX_EXTRACTED_CHARS:
        return text[:_MAX_EXTRACTED_CHARS].rstrip()
    return text
