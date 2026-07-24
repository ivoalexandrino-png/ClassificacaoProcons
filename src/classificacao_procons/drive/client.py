"""Cliente Google Drive para salvar PDFs de reclamações."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from classificacao_procons.google_auth import (
    DEFAULT_DRIVE_PARENT_FOLDER_ID,
    GoogleAuthError,
    load_credentials,
)

DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
DRIVE_PDF_MIME = "application/pdf"


class DriveClientError(RuntimeError):
    """Erro ao salvar arquivos no Google Drive."""


@dataclass(frozen=True)
class DriveUploadResult:
    consumer_folder_id: str
    consumer_folder_url: str
    pdf_file_id: str
    pdf_url: str


def _escape_drive_query_value(value: str) -> str:
    return value.replace("'", "\\'")


def _sanitize_folder_name(consumer_name: str) -> str:
    cleaned = " ".join(consumer_name.split()).strip()
    if not cleaned:
        raise DriveClientError("Nome da consumidora vazio.")
    return cleaned[:200]


def _sanitize_file_name_part(value: str) -> str:
    cleaned = " ".join(value.split()).strip()
    cleaned = re.sub(r'[\\/:*?"<>|]', "-", cleaned)
    return cleaned


def build_drive_pdf_filename(
    *,
    consumer_name: str,
    cip_number: str,
    complaint_date: date | None,
    doc_label: str = "Atendimento Procon",
) -> str:
    """Gera nome do PDF: Atendimento Procon - NOME - CIP - DATA."""
    safe_name = _sanitize_file_name_part(consumer_name)
    safe_cip = _sanitize_file_name_part(cip_number.replace("/", "-"))
    if complaint_date:
        safe_date = complaint_date.strftime("%d-%m-%Y")
    else:
        safe_date = "sem-data"

    if not safe_name:
        raise DriveClientError("Nome da consumidora vazio.")
    if not safe_cip:
        raise DriveClientError("Número da CIP vazio.")

    return f"{doc_label} - {safe_name} - {safe_cip} - {safe_date}.pdf"


def build_drive_pa_pdf_filename(
    *,
    consumer_name: str,
    administrative_process_number: str,
    complaint_date: date | None,
) -> str:
    """Gera nome do PDF de Processo Administrativo no Drive."""
    safe_pa = _sanitize_file_name_part(administrative_process_number.replace("/", "-"))
    if not safe_pa:
        raise DriveClientError("Número do processo administrativo vazio.")
    return build_drive_pdf_filename(
        consumer_name=consumer_name,
        cip_number=safe_pa,
        complaint_date=complaint_date,
        doc_label="Processo Administrativo Procon",
    )


def _build_drive_service(token_path: str | None = None):
    try:
        credentials = load_credentials(token_path or "credentials/gmail-token.json")
    except GoogleAuthError as exc:
        raise DriveClientError(str(exc)) from exc
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _find_child_folder(service, *, parent_id: str, folder_name: str) -> str | None:
    safe_name = _escape_drive_query_value(folder_name)
    query = (
        f"'{parent_id}' in parents and "
        f"name = '{safe_name}' and "
        f"mimeType = '{DRIVE_FOLDER_MIME}' and "
        "trashed = false"
    )
    try:
        response = (
            service.files()
            .list(q=query, fields="files(id)", pageSize=1, supportsAllDrives=True)
            .execute()
        )
    except HttpError as exc:
        raise DriveClientError(f"Falha ao buscar pasta no Drive: {exc}") from exc

    files = response.get("files", [])
    if not files:
        return None
    return files[0]["id"]


def _create_folder(service, *, parent_id: str, folder_name: str) -> str:
    body = {
        "name": folder_name,
        "mimeType": DRIVE_FOLDER_MIME,
        "parents": [parent_id],
    }
    try:
        created = (
            service.files()
            .create(body=body, fields="id, webViewLink", supportsAllDrives=True)
            .execute()
        )
    except HttpError as exc:
        raise DriveClientError(f"Falha ao criar pasta no Drive: {exc}") from exc
    return created["id"]


def ensure_consumer_folder(
    service,
    *,
    parent_folder_id: str,
    consumer_name: str,
) -> tuple[str, str]:
    """Retorna (folder_id, folder_url) da pasta da consumidora."""
    folder_name = _sanitize_folder_name(consumer_name)
    folder_id = _find_child_folder(service, parent_id=parent_folder_id, folder_name=folder_name)
    if not folder_id:
        folder_id = _create_folder(service, parent_id=parent_folder_id, folder_name=folder_name)

    try:
        metadata = (
            service.files()
            .get(fileId=folder_id, fields="webViewLink", supportsAllDrives=True)
            .execute()
        )
    except HttpError as exc:
        raise DriveClientError(f"Falha ao obter link da pasta: {exc}") from exc

    return folder_id, metadata["webViewLink"]


def upload_pdf_to_folder(
    service,
    *,
    folder_id: str,
    pdf_path: Path,
    file_name: str | None = None,
) -> tuple[str, str]:
    """Faz upload do PDF e retorna (file_id, file_url)."""
    if not pdf_path.exists():
        raise DriveClientError(f"PDF não encontrado: {pdf_path}")

    drive_file_name = file_name or pdf_path.name
    if not drive_file_name.lower().endswith(".pdf"):
        drive_file_name = f"{drive_file_name}.pdf"

    media = MediaFileUpload(str(pdf_path), mimetype=DRIVE_PDF_MIME, resumable=True)
    body = {"name": drive_file_name, "parents": [folder_id]}

    try:
        uploaded = (
            service.files()
            .create(
                body=body,
                media_body=media,
                fields="id, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
    except HttpError as exc:
        raise DriveClientError(f"Falha ao enviar PDF para o Drive: {exc}") from exc

    return uploaded["id"], uploaded["webViewLink"]


def ensure_folder_path(
    service,
    *,
    root_folder_id: str,
    path_parts: list[str],
) -> tuple[str, str]:
    """Garante uma cadeia de subpastas e retorna (folder_id, folder_url)."""
    if not path_parts:
        raise DriveClientError("Caminho de pastas vazio.")

    parent_id = root_folder_id
    for part in path_parts:
        folder_name = _sanitize_folder_name(part)
        folder_id = _find_child_folder(service, parent_id=parent_id, folder_name=folder_name)
        if not folder_id:
            folder_id = _create_folder(service, parent_id=parent_id, folder_name=folder_name)
        parent_id = folder_id

    try:
        metadata = (
            service.files()
            .get(fileId=parent_id, fields="webViewLink", supportsAllDrives=True)
            .execute()
        )
    except HttpError as exc:
        raise DriveClientError(f"Falha ao obter link da pasta: {exc}") from exc

    return parent_id, metadata["webViewLink"]


def upload_pdf_to_folder_path(
    *,
    root_folder_id: str,
    path_parts: list[str],
    pdf_path: Path,
    file_name: str | None = None,
    token_path: str | None = None,
) -> tuple[str, str, str]:
    """Cria/garante subpastas e envia PDF. Retorna (folder_id, folder_url, file_url)."""
    service = _build_drive_service(token_path)
    folder_id, folder_url = ensure_folder_path(
        service,
        root_folder_id=root_folder_id,
        path_parts=path_parts,
    )
    _, file_url = upload_pdf_to_folder(
        service,
        folder_id=folder_id,
        pdf_path=pdf_path,
        file_name=file_name,
    )
    return folder_id, folder_url, file_url


def save_complaint_pdf(
    *,
    consumer_name: str,
    pdf_path: str | Path,
    cip_number: str,
    complaint_date: date | None = None,
    parent_folder_id: str | None = None,
    token_path: str | None = None,
    file_name: str | None = None,
) -> DriveUploadResult:
    """
    Cria pasta da consumidora (se não existir) e envia o PDF.

    Retorna links da pasta e do arquivo.
    """
    parent_id = parent_folder_id or DEFAULT_DRIVE_PARENT_FOLDER_ID
    if not re.fullmatch(r"[\w-]+", parent_id):
        raise DriveClientError("ID da pasta pai do Drive inválido.")

    service = _build_drive_service(token_path)
    folder_id, folder_url = ensure_consumer_folder(
        service,
        parent_folder_id=parent_id,
        consumer_name=consumer_name,
    )
    file_id, file_url = upload_pdf_to_folder(
        service,
        folder_id=folder_id,
        pdf_path=Path(pdf_path),
        file_name=file_name
        or build_drive_pdf_filename(
            consumer_name=consumer_name,
            cip_number=cip_number,
            complaint_date=complaint_date,
        ),
    )

    return DriveUploadResult(
        consumer_folder_id=folder_id,
        consumer_folder_url=folder_url,
        pdf_file_id=file_id,
        pdf_url=file_url,
    )
