"""Monta o resumo do SAC a partir dos arquivos na pasta Informações (qualquer formato suportado)."""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from classificacao_procons.drive.client import DriveClientError
from classificacao_procons.drive.reader import (
    DRIVE_FOLDER_MIME,
    DriveFileInfo,
    SacFolderContext,
    download_drive_file,
)

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})
_MAX_CHARS_PER_FILE = 40_000
_MAX_TOTAL_CHARS = 120_000
_PLACEHOLDER_NO_TEXT = (
    "(Arquivo anexado pelo SAC; texto não extraído automaticamente neste formato.)"
)


def collect_sac_material_files(sac_context: SacFolderContext) -> tuple[DriveFileInfo, ...]:
    """Lista arquivos da pasta SAC a usar na elaboração (sem duplicar o PDF da CIP)."""
    seen: set[str] = set()
    ordered: list[DriveFileInfo] = []

    def add(file_info: DriveFileInfo | None) -> None:
        if file_info is None:
            return
        if file_info.mime_type == DRIVE_FOLDER_MIME:
            return
        if file_info.file_id in seen:
            return
        if file_info.file_id == sac_context.complaint_pdf.file_id:
            return
        seen.add(file_info.file_id)
        ordered.append(file_info)

    add(sac_context.summary_txt)
    for file_info in sac_context.supporting_files:
        add(file_info)

    def sort_key(file_info: DriveFileInfo) -> tuple[int, str]:
        name = file_info.name.casefold()
        if name.endswith(".txt") or file_info.mime_type.startswith("text/"):
            return (0, name)
        if name.endswith(".pdf") or file_info.mime_type == "application/pdf":
            return (1, name)
        return (2, name)

    return tuple(sorted(ordered, key=sort_key))


def _safe_local_name(file_name: str) -> str:
    cleaned = re.sub(r"[^\w.\- ()]", "_", file_name).strip()
    return cleaned or "anexo"


def _read_plain_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").strip()


def _extract_pdf_text_soft(path: Path, *, max_chars: int = _MAX_CHARS_PER_FILE) -> str:
    try:
        reader = PdfReader(str(path))
    except Exception:
        return ""
    parts: list[str] = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            parts.append(page_text)
    full_text = "\n".join(parts).strip()
    if len(full_text) > max_chars:
        return full_text[:max_chars].rstrip()
    return full_text


def extract_local_file_text(path: Path) -> str:
    """Extrai texto de um arquivo local (txt, pdf; demais formatos retornam vazio)."""
    suffix = path.suffix.casefold()
    if suffix == ".txt" or path.suffix == "":
        try:
            return _read_plain_text(path)
        except OSError:
            return ""
    if suffix == ".pdf":
        return _extract_pdf_text_soft(path)
    return ""


def _vision_extract_local_file_text(
    path: Path,
    *,
    gemini_api_key: str | None,
    gemini_model: str | None = None,
) -> str:
    suffix = path.suffix.casefold()
    if not gemini_api_key:
        return ""
    if suffix != ".pdf" and suffix not in _IMAGE_SUFFIXES:
        return ""

    from classificacao_procons.gemini.client import GeminiClientError
    from classificacao_procons.llm.document_vision import gemini_extract_text_from_document

    try:
        text = gemini_extract_text_from_document(
            path,
            api_key=gemini_api_key,
            model=gemini_model,
        )
    except GeminiClientError:
        return ""
    if len(text) > _MAX_CHARS_PER_FILE:
        return text[:_MAX_CHARS_PER_FILE].rstrip()
    return text


def build_sac_summary_from_drive_files(
    *,
    files: tuple[DriveFileInfo, ...] | list[DriveFileInfo],
    work_dir: Path,
    token_path: str | None = None,
    gemini_api_key: str | None = None,
    gemini_model: str | None = None,
) -> str:
    """Baixa arquivos do Drive e concatena o texto extraído para o prompt de elaboração."""
    if not files:
        raise DriveClientError("Pasta do SAC sem arquivos para elaboração.")

    work_dir.mkdir(parents=True, exist_ok=True)
    sections: list[str] = []
    total_chars = 0
    extracted_any = False

    for file_info in files:
        local_path = work_dir / _safe_local_name(file_info.name)
        try:
            download_drive_file(
                file_id=file_info.file_id,
                destination=local_path,
                token_path=token_path,
            )
        except DriveClientError as exc:
            sections.append(f"### {file_info.name}\n(Falha ao baixar: {exc})")
            continue

        body = extract_local_file_text(local_path)
        if not body.strip():
            body = _vision_extract_local_file_text(
                local_path,
                gemini_api_key=gemini_api_key,
                gemini_model=gemini_model,
            )
        if body.strip():
            extracted_any = True
            section = f"### {file_info.name}\n{body.strip()}"
        else:
            section = f"### {file_info.name}\n{_PLACEHOLDER_NO_TEXT}"

        if total_chars + len(section) > _MAX_TOTAL_CHARS:
            section = section[: max(0, _MAX_TOTAL_CHARS - total_chars)].rstrip()
            sections.append(section)
            break

        sections.append(section)
        total_chars += len(section)

    if not extracted_any:
        raise DriveClientError(
            "Nenhum texto extraído dos arquivos do SAC (PDFs só imagem ou formatos não legíveis).",
        )

    return "\n\n".join(sections).strip()
