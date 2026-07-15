"""Leitura de arquivos do Google Drive para elaboração de resposta."""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from classificacao_procons.drive.client import (
    DRIVE_FOLDER_MIME,
    DriveClientError,
    _build_drive_service,
)

DRIVE_TEXT_MIME = "text/plain"
PROCON_PDF_PREFIX = "atendimento procon"
RESPONSE_OUTPUT_FOLDER = "Resposta Automatica"
SAC_FOLDER_KEYWORDS = ("informacoes", "sac", "anexos", "documentos")


@dataclass(frozen=True)
class DriveFileInfo:
    file_id: str
    name: str
    mime_type: str
    created_time: datetime | None
    web_view_link: str | None = None


@dataclass(frozen=True)
class SacFolderContext:
    consumer_folder_id: str
    sac_folder_id: str
    complaint_pdf: DriveFileInfo
    summary_txt: DriveFileInfo | None
    supporting_files: list[DriveFileInfo]


def extract_drive_resource_id(url: str) -> str:
    """Extrai ID de pasta ou arquivo de URLs do Google Drive."""
    patterns = (
        r"/folders/([\w-]+)",
        r"/file/d/([\w-]+)",
        r"id=([\w-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise DriveClientError("URL do Google Drive inválida.")


def _parse_drive_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _list_children(service, *, folder_id: str) -> list[DriveFileInfo]:
    query = f"'{folder_id}' in parents and trashed = false"
    try:
        response = (
            service.files()
            .list(
                q=query,
                fields="files(id,name,mimeType,createdTime,webViewLink)",
                pageSize=200,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
    except HttpError as exc:
        raise DriveClientError(f"Falha ao listar pasta do Drive: {exc}") from exc

    files: list[DriveFileInfo] = []
    for item in response.get("files", []):
        files.append(
            DriveFileInfo(
                file_id=item["id"],
                name=item["name"],
                mime_type=item.get("mimeType", ""),
                created_time=_parse_drive_timestamp(item.get("createdTime")),
                web_view_link=item.get("webViewLink"),
            ),
        )
    return files


def _get_file_metadata(service, *, file_id: str) -> DriveFileInfo:
    try:
        item = (
            service.files()
            .get(
                fileId=file_id,
                fields="id,name,mimeType,createdTime,webViewLink,parents",
                supportsAllDrives=True,
            )
            .execute()
        )
    except HttpError as exc:
        raise DriveClientError(f"Falha ao obter metadados do Drive: {exc}") from exc

    return DriveFileInfo(
        file_id=item["id"],
        name=item["name"],
        mime_type=item.get("mimeType", ""),
        created_time=_parse_drive_timestamp(item.get("createdTime")),
        web_view_link=item.get("webViewLink"),
    )


def _get_parent_folder_id(service, *, folder_id: str) -> str | None:
    try:
        item = (
            service.files()
            .get(fileId=folder_id, fields="parents", supportsAllDrives=True)
            .execute()
        )
    except HttpError as exc:
        raise DriveClientError(f"Falha ao obter pasta pai no Drive: {exc}") from exc
    parents = item.get("parents", [])
    if not parents:
        return None
    return parents[0]


def _is_pdf(file_info: DriveFileInfo) -> bool:
    return file_info.mime_type == "application/pdf" or file_info.name.lower().endswith(".pdf")


def _is_txt(file_info: DriveFileInfo) -> bool:
    return file_info.mime_type.startswith("text/") or file_info.name.lower().endswith(".txt")


def _is_complaint_pdf(file_info: DriveFileInfo) -> bool:
    return _is_pdf(file_info) and file_info.name.casefold().startswith(PROCON_PDF_PREFIX)


def _normalize_folder_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


def _score_sac_folder_name(name: str) -> int:
    normalized = _normalize_folder_name(name)
    for index, keyword in enumerate(SAC_FOLDER_KEYWORDS):
        if keyword in normalized:
            return 100 - index
    return 0


def _find_complaint_pdf(files: list[DriveFileInfo]) -> DriveFileInfo | None:
    candidates = [file_info for file_info in files if _is_complaint_pdf(file_info)]
    if not candidates:
        candidates = [file_info for file_info in files if _is_pdf(file_info)]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.created_time or datetime.min)
    return candidates[0]


def _find_summary_txt(files: list[DriveFileInfo]) -> DriveFileInfo | None:
    txt_files = [file_info for file_info in files if _is_txt(file_info)]
    if not txt_files:
        return None

    def sort_key(file_info: DriveFileInfo) -> tuple[int, datetime]:
        normalized = _normalize_folder_name(file_info.name)
        keyword_score = 1 if "inform" in normalized or "resumo" in normalized else 0
        created = file_info.created_time or datetime.min
        return (keyword_score, created)

    txt_files.sort(key=sort_key, reverse=True)
    return txt_files[0]


def _select_sac_subfolder(subfolders: list[DriveFileInfo]) -> DriveFileInfo | None:
    if not subfolders:
        return None
    ranked = sorted(
        subfolders,
        key=lambda folder: (
            _score_sac_folder_name(folder.name),
            folder.created_time or datetime.min,
        ),
        reverse=True,
    )
    if ranked[0] and _score_sac_folder_name(ranked[0].name) > 0:
        return ranked[0]
    ranked.sort(key=lambda folder: folder.created_time or datetime.min, reverse=True)
    return ranked[0]


def resolve_sac_folder_context(
    *,
    docs_sac_url: str,
    token_path: str | None = None,
) -> SacFolderContext:
    """Localiza PDF original, pasta SAC e resumo TXT a partir do link do Monday."""
    service = _build_drive_service(token_path)
    linked_id = extract_drive_resource_id(docs_sac_url)
    linked_metadata = _get_file_metadata(service, file_id=linked_id)

    if linked_metadata.mime_type == DRIVE_FOLDER_MIME:
        linked_children = _list_children(service, folder_id=linked_id)
        complaint_pdf = _find_complaint_pdf(linked_children)
        if complaint_pdf is not None:
            subfolders = [
                item for item in linked_children if item.mime_type == DRIVE_FOLDER_MIME
            ]
            sac_folder = _select_sac_subfolder(subfolders)
            if sac_folder is None:
                raise DriveClientError("Subpasta do SAC não encontrada na pasta do caso.")
            sac_children = _list_children(service, folder_id=sac_folder.file_id)
            summary_txt = _find_summary_txt(sac_children)
            return SacFolderContext(
                consumer_folder_id=linked_id,
                sac_folder_id=sac_folder.file_id,
                complaint_pdf=complaint_pdf,
                summary_txt=summary_txt,
                supporting_files=[
                    item
                    for item in sac_children
                    if summary_txt is None or item.file_id != summary_txt.file_id
                ],
            )

        summary_txt = _find_summary_txt(linked_children)
        if summary_txt is not None:
            parent_id = _get_parent_folder_id(service, folder_id=linked_id)
            if parent_id is None:
                raise DriveClientError("Não foi possível localizar a pasta principal do caso.")
            parent_children = _list_children(service, folder_id=parent_id)
            complaint_pdf = _find_complaint_pdf(parent_children)
            if complaint_pdf is None:
                raise DriveClientError("PDF original da reclamação não encontrado no Drive.")
            return SacFolderContext(
                consumer_folder_id=parent_id,
                sac_folder_id=linked_id,
                complaint_pdf=complaint_pdf,
                summary_txt=summary_txt,
                supporting_files=[
                    item for item in linked_children if item.file_id != summary_txt.file_id
                ],
            )

        raise DriveClientError("Pasta do SAC sem documentos reconhecíveis.")

    raise DriveClientError("Link em Docs SAC deve apontar para uma pasta do Drive.")


def download_drive_file(
    *,
    file_id: str,
    destination: Path,
    token_path: str | None = None,
) -> Path:
    service = _build_drive_service(token_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        with io.FileIO(destination, "wb") as output:
            downloader = MediaIoBaseDownload(output, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
    except HttpError as exc:
        raise DriveClientError(f"Falha ao baixar arquivo do Drive: {exc}") from exc
    return destination


def ensure_output_folder(
    *,
    parent_folder_id: str,
    folder_name: str = RESPONSE_OUTPUT_FOLDER,
    token_path: str | None = None,
) -> str:
    service = _build_drive_service(token_path)
    children = _list_children(service, folder_id=parent_folder_id)
    for child in children:
        if child.mime_type == DRIVE_FOLDER_MIME and child.name == folder_name:
            return child.file_id

    body = {"name": folder_name, "mimeType": DRIVE_FOLDER_MIME, "parents": [parent_folder_id]}
    try:
        created = (
            service.files()
            .create(body=body, fields="id", supportsAllDrives=True)
            .execute()
        )
    except HttpError as exc:
        raise DriveClientError(f"Falha ao criar pasta de resposta no Drive: {exc}") from exc
    return created["id"]


def upload_text_file(
    *,
    folder_id: str,
    file_name: str,
    content: str,
    token_path: str | None = None,
) -> str:
    service = _build_drive_service(token_path)
    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype=DRIVE_TEXT_MIME,
        resumable=True,
    )
    body = {"name": file_name, "parents": [folder_id]}
    try:
        uploaded = (
            service.files()
            .create(
                body=body,
                media_body=media,
                fields="id,webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
    except HttpError as exc:
        raise DriveClientError(f"Falha ao enviar arquivo de texto para o Drive: {exc}") from exc
    return uploaded.get("webViewLink", "")
