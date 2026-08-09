"""Coleta texto da reclamação e indícios no Drive."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from classificacao_procons.drive.client import DRIVE_FOLDER_MIME
from classificacao_procons.drive.reader import (
    download_drive_file,
    is_procon_complaint_pdf,
)
from classificacao_procons.juridico.casos_consumidor.deposits_loader import ConsumerDepositSummary
from classificacao_procons.juridico.depositos.drive_crawl import (
    list_children_paginated,
    walk_pdfs_under_folder,
)
from classificacao_procons.juridico.depositos.fields import extract_process_number
from classificacao_procons.juridico.depositos.text_extract import extract_pdf_text

_MAX_COMPLAINT_CHARS = 14_000
_CNJ_FROM_NAME = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")


@dataclass(frozen=True)
class ConsumerDriveContext:
    consumer_folder: str
    folder_id: str
    complaint_text: str
    process_numbers: tuple[str, ...]
    has_sentence_pdf: bool
    sentence_text: str | None


def _collect_cnj_from_paths(paths: list[str]) -> set[str]:
    found: set[str] = set()
    for path in paths:
        for match in _CNJ_FROM_NAME.finditer(path):
            found.add(match.group(0))
    return found


def _find_sentence_pdf(paths: list[str]) -> str | None:
    for path in paths:
        normalized = path.casefold()
        if "sentenca" in normalized or "sentença" in normalized:
            return path
    return None


def build_consumer_context(
    *,
    consumer_name: str,
    folder_id: str,
    work_dir: Path,
    token_path: str | None,
    deposit_summary: ConsumerDepositSummary | None,
    gemini_api_key: str | None,
) -> ConsumerDriveContext:
    from classificacao_procons.drive.client import _build_drive_service

    service = _build_drive_service(token_path)
    children = list_children_paginated(service, folder_id=folder_id)
    pdfs = walk_pdfs_under_folder(folder_id=folder_id, path_prefix=consumer_name, max_depth=5)
    path_list = [item.drive_path for item in pdfs]
    process_numbers = _collect_cnj_from_paths(path_list)
    if deposit_summary:
        process_numbers.update(deposit_summary.process_numbers)

    complaint_text = ""
    for item in children:
        if item.mime_type == DRIVE_FOLDER_MIME:
            continue
        if is_procon_complaint_pdf(item):
            local = work_dir / consumer_name / "complaint.pdf"
            download_drive_file(file_id=item.file_id, destination=local, token_path=token_path)
            extracted = extract_pdf_text(
                local,
                gemini_api_key=gemini_api_key,
                allow_vision=bool(gemini_api_key),
            )
            complaint_text = extracted.text[:_MAX_COMPLAINT_CHARS]
            cnj = extract_process_number(complaint_text)
            if cnj:
                process_numbers.add(cnj)
            break

    if not complaint_text:
        for item in children:
            if item.mime_type != DRIVE_FOLDER_MIME and item.name.casefold().endswith(".pdf"):
                local = work_dir / consumer_name / "fallback.pdf"
                download_drive_file(file_id=item.file_id, destination=local, token_path=token_path)
                extracted = extract_pdf_text(
                    local,
                    gemini_api_key=gemini_api_key,
                    allow_vision=False,
                )
                if len(extracted.text.strip()) > 200:
                    complaint_text = extracted.text[:_MAX_COMPLAINT_CHARS]
                    cnj = extract_process_number(complaint_text)
                    if cnj:
                        process_numbers.add(cnj)
                    break

    sentence_path = _find_sentence_pdf(path_list)
    sentence_text: str | None = None
    if sentence_path:
        match = next((p for p in pdfs if p.drive_path == sentence_path), None)
        if match:
            local = work_dir / consumer_name / "sentence.pdf"
            download_drive_file(file_id=match.file_id, destination=local, token_path=token_path)
            extracted = extract_pdf_text(
                local,
                gemini_api_key=gemini_api_key,
                allow_vision=bool(gemini_api_key),
            )
            sentence_text = extracted.text[:_MAX_COMPLAINT_CHARS]

    return ConsumerDriveContext(
        consumer_folder=consumer_name,
        folder_id=folder_id,
        complaint_text=complaint_text,
        process_numbers=tuple(sorted(process_numbers)),
        has_sentence_pdf=sentence_path is not None,
        sentence_text=sentence_text,
    )
