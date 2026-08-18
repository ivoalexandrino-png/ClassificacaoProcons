"""Orquestração PLAN/APPLY para item.assets (metadata vs materialização)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from classificacao_procons.migration.asset_attachment import (
    ensure_sunday_link_attachment,
    plan_sunday_attachment,
)
from classificacao_procons.migration.asset_models import (
    MaterializedAsset,
    MondayAssetMetadata,
    StorageObjectRecord,
)
from classificacao_procons.migration.asset_storage import (
    StoragePort,
    build_storage_object_key,
    resolve_or_upload_storage_object,
)
from classificacao_procons.migration.asset_verifier import AssetVerificationReport
from classificacao_procons.migration.dispositions import Disposition
from classificacao_procons.migration.monday_asset_download import (
    download_monday_asset,
    materialized_matches_metadata,
    sanitize_asset_filename,
)
from classificacao_procons.migration.operation_manifest import payload_digest


@dataclass
class BinaryAssetApplyStats:
    asset_downloads: int = 0
    storage_uploads: int = 0
    storage_adopts: int = 0
    attachment_link_writes: int = 0
    attachment_link_skipped: int = 0


@dataclass
class BinaryItemDryRunRow:
    monday_item_id: str
    asset_count: int
    disposition: str
    classification: str
    blocked_reason: str
    completeness_ok: bool
    ready: bool
    deferred_reason: str = ""


@dataclass
class BinaryWaveDryRunReport:
    items: list[BinaryItemDryRunRow] = field(default_factory=list)

    @property
    def item_count(self) -> int:
        return len(self.items)

    @property
    def asset_count(self) -> int:
        return sum(row.asset_count for row in self.items)

    @property
    def ready_count(self) -> int:
        return sum(1 for row in self.items if row.ready)


class AssetDownloader(Protocol):
    def __call__(
        self,
        api_token: str,
        asset: MondayAssetMetadata,
    ) -> MaterializedAsset: ...


def attachment_payload_digest(asset: MondayAssetMetadata) -> str:
    sanitized = sanitize_asset_filename(
        asset.name,
        asset_id=asset.asset_id,
        extension=asset.file_extension,
    )
    storage_key = build_storage_object_key(
        board_id=asset.board_id,
        item_id=asset.item_id,
        asset_id=asset.asset_id,
        sanitized_filename=sanitized,
    )
    return payload_digest(
        {
            "board_id": asset.board_id,
            "item_id": asset.item_id,
            "asset_id": asset.asset_id,
            "filename": asset.name,
            "file_size": asset.file_size,
            "file_extension": asset.file_extension,
            "created_at": asset.created_at,
            "storage_key": storage_key,
            "operation": "sunday_link_attachment",
        },
    )


ALLOWED_ASSET_EXTENSIONS = frozenset({"pdf", "jpg", "jpeg"})


def validate_asset_extension(asset: MondayAssetMetadata) -> None:
    from classificacao_procons.migration.asset_models import MigrationAssetError

    extension = (asset.file_extension or "").lower().lstrip(".")
    if extension and extension not in ALLOWED_ASSET_EXTENSIONS:
        raise MigrationAssetError(
            f"Tipo de asset não suportado: {extension or 'desconhecido'}.",
        )


def apply_single_asset(
    *,
    api_token: str,
    sunday_client,
    sunday_item_id: str,
    expected: MondayAssetMetadata,
    storage: StoragePort,
    stats: BinaryAssetApplyStats | None = None,
    downloader: AssetDownloader | None = None,
) -> StorageObjectRecord:
    validate_asset_extension(expected)
    download_fn = downloader or download_monday_asset
    materialized = download_fn(api_token, expected)
    materialized_matches_metadata(materialized, expected)
    if stats is not None:
        stats.asset_downloads += 1

    record = resolve_or_upload_storage_object(backend=storage, materialized=materialized)
    if stats is not None:
        if record.action == "UPLOAD_REQUIRED":
            stats.storage_uploads += 1
        elif record.action == "ADOPT_EXISTING_STORAGE_OBJECT":
            stats.storage_adopts += 1

    attachment_plan = plan_sunday_attachment(asset=expected, storage=record)
    _, created = ensure_sunday_link_attachment(
        sunday_client,
        sunday_item_id=sunday_item_id,
        plan=attachment_plan,
    )
    if stats is not None:
        if created:
            stats.attachment_link_writes += 1
        else:
            stats.attachment_link_skipped += 1
    return record


def apply_item_assets(
    *,
    api_token: str,
    sunday_client,
    sunday_item_id: str,
    expected_assets: tuple[MondayAssetMetadata, ...],
    storage: StoragePort,
    stats: BinaryAssetApplyStats | None = None,
    downloader: AssetDownloader | None = None,
) -> tuple[StorageObjectRecord, ...]:
    records: list[StorageObjectRecord] = []
    for asset in sorted(expected_assets, key=lambda row: row.asset_id):
        records.append(
            apply_single_asset(
                api_token=api_token,
                sunday_client=sunday_client,
                sunday_item_id=sunday_item_id,
                expected=asset,
                storage=storage,
                stats=stats,
                downloader=downloader,
            ),
        )
    return tuple(records)


def verify_item_assets(
    *,
    expected_assets: tuple[MondayAssetMetadata, ...],
    storage: StoragePort,
    sunday_attachments,
    materialized_by_asset: dict[str, MaterializedAsset],
) -> AssetVerificationReport:
    from classificacao_procons.migration.asset_verifier import (
        AssetVerificationRow,
        verify_materialized_asset,
    )

    report = AssetVerificationReport()
    for asset in sorted(expected_assets, key=lambda row: row.asset_id):
        materialized = materialized_by_asset.get(asset.asset_id)
        if materialized is None:
            report.rows.append(
                AssetVerificationRow(
                    asset_id=asset.asset_id,
                    result="SOURCE_ASSET_CHANGED",
                    detail="materialized asset ausente",
                ),
            )
            continue
        storage_key = build_storage_object_key(
            board_id=asset.board_id,
            item_id=asset.item_id,
            asset_id=asset.asset_id,
            sanitized_filename=materialized.sanitized_filename,
        )
        report.rows.append(
            verify_materialized_asset(
                expected=asset,
                materialized_sha256=materialized.sha256,
                materialized_size=len(materialized.content),
                storage=storage,
                storage_key=storage_key,
                sunday_attachments=sunday_attachments,
            ),
        )
    return report


def classify_binary_item_ready(
    *,
    disposition: Disposition | str,
    classification: str,
    blocked_reason: str | None,
    completeness_ok: bool,
    asset_count: int,
) -> tuple[bool, str]:
    if asset_count <= 0:
        return False, "NO_BINARY_ASSETS"
    if classification in {"MANUAL", "ERROR"}:
        return False, classification
    if blocked_reason:
        return False, "blocked"
    if str(disposition) not in {Disposition.CREATE.value, "CREATE"}:
        return False, f"disposition_{disposition}"
    if not completeness_ok:
        return False, "completeness_fail"
    if asset_count > 1:
        return True, "MULTIPLE_ASSETS"
    return True, "BINARY_UPLOAD_REQUIRED"
