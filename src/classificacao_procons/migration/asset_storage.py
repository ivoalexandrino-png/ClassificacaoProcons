"""Storage externo durável para assets migrados (Google Drive reutilizado)."""

from __future__ import annotations

import hashlib
import io
import os
import re
from dataclasses import dataclass

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from classificacao_procons.drive.client import (
    DriveClientError,
    _build_drive_service,
    _escape_drive_query_value,
    ensure_folder_path,
)
from classificacao_procons.migration.asset_models import (
    MaterializedAsset,
    MigrationAssetError,
    StorageBackendMissingError,
    StorageObjectRecord,
)

ENV_MIGRATION_ASSETS_ROOT = "MIGRATION_ASSETS_DRIVE_ROOT_FOLDER_ID"
APP_PROP_KEY = "migration_asset_key"
APP_PROP_SHA256 = "migration_sha256"


@dataclass(frozen=True)
class StorageBackendConfig:
    root_folder_id: str
    token_path: str | None = None


def migration_storage_config_from_env() -> StorageBackendConfig:
    root = os.environ.get(ENV_MIGRATION_ASSETS_ROOT, "").strip()
    if not root or not re.fullmatch(r"[\w-]+", root):
        raise StorageBackendMissingError(
            f"{ENV_MIGRATION_ASSETS_ROOT} ausente ou inválido para storage de assets.",
        )
    token_path = os.environ.get("GMAIL_TOKEN_PATH", "credentials/gmail-token.json").strip()
    return StorageBackendConfig(root_folder_id=root, token_path=token_path or None)


def build_storage_object_key(
    *,
    board_id: str,
    item_id: str,
    asset_id: str,
    sanitized_filename: str,
) -> str:
    return f"monday/{board_id}/{item_id}/{asset_id}/{sanitized_filename}"


def build_storage_path_parts(storage_key: str) -> list[str]:
    return storage_key.split("/")


def build_drive_file_name(storage_key: str) -> str:
    return storage_key.replace("/", "__")


class StoragePort:
    """Porta injetável para testes (mock) e Drive (produção)."""

    def resolve(self, storage_key: str) -> StorageObjectRecord | None:
        raise NotImplementedError

    def upload(self, *, storage_key: str, materialized: MaterializedAsset) -> StorageObjectRecord:
        raise NotImplementedError


class DriveStorageBackend(StoragePort):
    def __init__(self, config: StorageBackendConfig) -> None:
        self._config = config
        self._service = _build_drive_service(config.token_path)

    def resolve(self, storage_key: str) -> StorageObjectRecord | None:
        safe_key = _escape_drive_query_value(storage_key)
        query = (
            f"appProperties has {{ key='{APP_PROP_KEY}' and value='{safe_key}' }} "
            "and trashed = false"
        )
        try:
            response = (
                self._service.files()
                .list(
                    q=query,
                    fields="files(id, name, webViewLink, size, appProperties)",
                    pageSize=1,
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise DriveClientError(f"Falha ao buscar objeto storage: {exc}") from exc
        files = response.get("files") or []
        if not files:
            return None
        row = files[0]
        props = row.get("appProperties") or {}
        return StorageObjectRecord(
            storage_key=storage_key,
            drive_file_id=str(row["id"]),
            public_url=str(row.get("webViewLink") or ""),
            sha256=str(props.get(APP_PROP_SHA256) or ""),
            size=int(row.get("size") or 0),
            mime_type=materialized_mime_placeholder(),
            original_filename=row.get("name") or build_drive_file_name(storage_key),
            action="ADOPT_EXISTING_STORAGE_OBJECT",
        )

    def upload(self, *, storage_key: str, materialized: MaterializedAsset) -> StorageObjectRecord:
        existing = self.resolve(storage_key)
        if existing is not None:
            if existing.sha256 and existing.sha256 != materialized.sha256:
                raise MigrationAssetError(
                    f"CONFLICT storage {storage_key}: hash existente diverge.",
                )
            if existing.size and existing.size != len(materialized.content):
                raise MigrationAssetError(
                    f"CONFLICT storage {storage_key}: size diverge.",
                )
            return StorageObjectRecord(
                storage_key=storage_key,
                drive_file_id=existing.drive_file_id,
                public_url=existing.public_url,
                sha256=materialized.sha256,
                size=len(materialized.content),
                mime_type=materialized.mime_type,
                original_filename=materialized.sanitized_filename,
                action="ADOPT_EXISTING_STORAGE_OBJECT",
            )

        path_parts = build_storage_path_parts(storage_key)[:-1]
        folder_id, _folder_url = ensure_folder_path(
            self._service,
            root_folder_id=self._config.root_folder_id,
            path_parts=path_parts,
        )
        drive_name = build_drive_file_name(storage_key)
        media = MediaIoBaseUpload(
            io.BytesIO(materialized.content),
            mimetype=materialized.mime_type,
            resumable=True,
        )
        body = {
            "name": drive_name,
            "parents": [folder_id],
            "appProperties": {
                APP_PROP_KEY: storage_key,
                APP_PROP_SHA256: materialized.sha256,
            },
        }
        try:
            uploaded = (
                self._service.files()
                .create(
                    body=body,
                    media_body=media,
                    fields="id, webViewLink, size",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise DriveClientError(f"Falha upload asset storage: {exc}") from exc

        return StorageObjectRecord(
            storage_key=storage_key,
            drive_file_id=str(uploaded["id"]),
            public_url=str(uploaded.get("webViewLink") or ""),
            sha256=materialized.sha256,
            size=len(materialized.content),
            mime_type=materialized.mime_type,
            original_filename=materialized.sanitized_filename,
            action="UPLOAD_REQUIRED",
        )


def materialized_mime_placeholder() -> str:
    return "application/octet-stream"


def resolve_or_upload_storage_object(
    *,
    backend: StoragePort,
    materialized: MaterializedAsset,
) -> StorageObjectRecord:
    storage_key = build_storage_object_key(
        board_id=materialized.metadata.board_id,
        item_id=materialized.metadata.item_id,
        asset_id=materialized.metadata.asset_id,
        sanitized_filename=materialized.sanitized_filename,
    )
    return backend.upload(storage_key=storage_key, materialized=materialized)


def storage_payload_digest_fields(
    *,
    asset: MaterializedAsset,
    storage_key: str,
) -> dict[str, object]:
    return {
        "board_id": asset.metadata.board_id,
        "item_id": asset.metadata.item_id,
        "asset_id": asset.metadata.asset_id,
        "filename": asset.sanitized_filename,
        "mime_type": asset.mime_type,
        "size": len(asset.content),
        "sha256": asset.sha256,
        "storage_key": storage_key,
        "operation": "sunday_link_attachment",
    }


def storage_key_digest(storage_key: str) -> str:
    return hashlib.sha256(storage_key.encode("utf-8")).hexdigest()
