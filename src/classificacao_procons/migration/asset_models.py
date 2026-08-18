"""Modelos canônicos para materialização Monday item.assets → storage → Sunday."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StorageResolveAction = Literal[
    "UPLOAD_REQUIRED",
    "ADOPT_EXISTING_STORAGE_OBJECT",
    "CONFLICT",
]

AssetVerifyResult = Literal[
    "MATCH",
    "MISSING_STORAGE",
    "STORAGE_HASH_MISMATCH",
    "MISSING_SUNDAY_ATTACHMENT",
    "DUPLICATE_SUNDAY_ATTACHMENT",
    "SOURCE_ASSET_CHANGED",
    "AMBIGUOUS",
]


@dataclass(frozen=True)
class MondayAssetMetadata:
    """Metadata estável para PLAN/fingerprint (sem URL Monday)."""

    board_id: str
    item_id: str
    asset_id: str
    name: str
    file_size: int | None
    file_extension: str | None
    created_at: str | None = None

    @property
    def fingerprint_tuple(self) -> tuple[str, str | None, int | None, str | None, str | None]:
        return (
            self.asset_id,
            self.name,
            self.file_size,
            self.file_extension,
            self.created_at,
        )


@dataclass(frozen=True)
class MaterializedAsset:
    metadata: MondayAssetMetadata
    content: bytes
    sha256: str
    mime_type: str
    sanitized_filename: str


@dataclass(frozen=True)
class StorageObjectRecord:
    storage_key: str
    drive_file_id: str
    public_url: str
    sha256: str
    size: int
    mime_type: str
    original_filename: str
    action: StorageResolveAction


@dataclass(frozen=True)
class SundayAttachmentPlan:
    board_id: str
    item_id: str
    asset_id: str
    storage_url: str
    attachment_filename: str
    marker: str


class MigrationAssetError(RuntimeError):
    """Falha fail-closed na pipeline de assets."""


class StorageBackendMissingError(MigrationAssetError):
    """Backend de storage externo não configurado/disponível."""
