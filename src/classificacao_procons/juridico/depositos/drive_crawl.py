"""Varredura de pastas de consumidores no Google Drive."""

from __future__ import annotations

from dataclasses import dataclass

from classificacao_procons.drive.client import DRIVE_FOLDER_MIME, _build_drive_service
from classificacao_procons.drive.reader import DriveFileInfo, _parse_drive_timestamp
from classificacao_procons.juridico.depositos.path_rules import path_suggests_deposit_workflow

_NON_DOWNLOADABLE_PREFIX = "application/vnd.google-apps."

@dataclass(frozen=True)
class DrivePdfItem:
    file_id: str
    name: str
    drive_path: str
    web_view_link: str | None
    mime_type: str


def list_children_paginated(service, *, folder_id: str) -> list[DriveFileInfo]:
    query = f"'{folder_id}' in parents and trashed = false"
    page_token: str | None = None
    files: list[DriveFileInfo] = []
    while True:
        response = (
            service.files()
            .list(
                q=query,
                fields="nextPageToken,files(id,name,mimeType,createdTime,webViewLink)",
                pageSize=200,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
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
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return files


def list_consumer_folders(
    *,
    root_folder_id: str,
    token_path: str | None = None,
    max_consumers: int | None = None,
) -> list[DriveFileInfo]:
    service = _build_drive_service(token_path)
    children = list_children_paginated(service, folder_id=root_folder_id)
    folders = [item for item in children if item.mime_type == DRIVE_FOLDER_MIME]
    folders.sort(key=lambda item: item.name.casefold())
    if max_consumers is not None:
        return folders[:max_consumers]
    return folders


def walk_pdfs_under_folder(
    *,
    folder_id: str,
    path_prefix: str,
    token_path: str | None = None,
    max_depth: int = 6,
    _depth: int = 0,
) -> list[DrivePdfItem]:
    if _depth > max_depth:
        return []
    service = _build_drive_service(token_path)
    items = list_children_paginated(service, folder_id=folder_id)
    collected: list[DrivePdfItem] = []
    for item in items:
        child_path = f"{path_prefix}/{item.name}" if path_prefix else item.name
        if item.mime_type == DRIVE_FOLDER_MIME:
            collected.extend(
                walk_pdfs_under_folder(
                    folder_id=item.file_id,
                    path_prefix=child_path,
                    token_path=token_path,
                    max_depth=max_depth,
                    _depth=_depth + 1,
                ),
            )
            continue
        if item.mime_type.startswith(_NON_DOWNLOADABLE_PREFIX):
            continue
        is_pdf = item.mime_type == "application/pdf" or item.name.casefold().endswith(".pdf")
        if is_pdf or path_suggests_deposit_workflow(child_path):
            collected.append(
                DrivePdfItem(
                    file_id=item.file_id,
                    name=item.name,
                    drive_path=child_path,
                    web_view_link=item.web_view_link,
                    mime_type=item.mime_type,
                ),
            )
    return collected
