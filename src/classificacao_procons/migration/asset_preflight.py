"""Materialização read-only para approval final e pre-write gate do APPLY."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from classificacao_procons.migration.asset_models import (
    ApprovedBinaryAsset,
    MaterializedAsset,
    MigrationAssetError,
    MondayAssetMetadata,
)
from classificacao_procons.migration.asset_storage import build_storage_object_key
from classificacao_procons.migration.monday_asset_download import (
    download_monday_asset,
    materialized_matches_metadata,
    validate_asset_extension,
)


class AssetDownloader(Protocol):
    def __call__(
        self,
        api_token: str,
        asset: MondayAssetMetadata,
    ) -> MaterializedAsset: ...


@dataclass(frozen=True)
class PreflightBatchResult:
    approved_assets: tuple[ApprovedBinaryAsset, ...]
    materialized_by_asset_id: dict[str, MaterializedAsset]


def approved_binary_asset_from_materialized(
    *,
    materialized: MaterializedAsset,
    sunday_board_id: str,
) -> ApprovedBinaryAsset:
    meta = materialized.metadata
    storage_key = build_storage_object_key(
        board_id=meta.board_id,
        item_id=meta.item_id,
        asset_id=meta.asset_id,
        sanitized_filename=materialized.sanitized_filename,
    )
    return ApprovedBinaryAsset(
        board_id=meta.board_id,
        monday_item_id=meta.item_id,
        asset_id=meta.asset_id,
        sanitized_filename=materialized.sanitized_filename,
        mime_type=materialized.mime_type,
        size=len(materialized.content),
        source_sha256=materialized.sha256,
        storage_object_key=storage_key,
        sunday_board_id=sunday_board_id,
    )


def materialize_asset_readonly(
    api_token: str,
    asset: MondayAssetMetadata,
    *,
    downloader: AssetDownloader | None = None,
    temp_dir: Path | None = None,
) -> MaterializedAsset:
    """Download read-only; opcionalmente persiste bytes em temp_dir (nunca git)."""
    validate_asset_extension(asset)
    download_fn = downloader or download_monday_asset
    materialized = download_fn(api_token, asset)
    materialized_matches_metadata(materialized, asset)
    if temp_dir is not None:
        target = temp_dir / f"{asset.asset_id}.bin"
        target.write_bytes(materialized.content)
    return materialized


def build_final_approval_assets(
    api_token: str,
    *,
    assets_by_item: dict[str, tuple[MondayAssetMetadata, ...]],
    sunday_board_id: str,
    downloader: AssetDownloader | None = None,
) -> PreflightBatchResult:
    """PLAN final read-only: baixa bytes, calcula SHA256, sem Drive/Sunday writes."""
    approved: list[ApprovedBinaryAsset] = []
    materialized_by_id: dict[str, MaterializedAsset] = {}
    with tempfile.TemporaryDirectory(prefix="migration-asset-preflight-") as tmp_raw:
        temp_dir = Path(tmp_raw)
        for item_id in sorted(assets_by_item):
            for asset in sorted(assets_by_item[item_id], key=lambda row: row.asset_id):
                materialized = materialize_asset_readonly(
                    api_token,
                    asset,
                    downloader=downloader,
                    temp_dir=temp_dir,
                )
                materialized_by_id[asset.asset_id] = materialized
                approved.append(
                    approved_binary_asset_from_materialized(
                        materialized=materialized,
                        sunday_board_id=sunday_board_id,
                    ),
                )
    return PreflightBatchResult(
        approved_assets=tuple(approved),
        materialized_by_asset_id=materialized_by_id,
    )


def runtime_preflight_verify_batch(
    api_token: str,
    *,
    assets_by_item: dict[str, tuple[MondayAssetMetadata, ...]],
    approved_by_asset_id: dict[str, ApprovedBinaryAsset],
    downloader: AssetDownloader | None = None,
) -> PreflightBatchResult:
    """APPLY pre-write gate: materializa TODOS os assets antes de qualquer write."""
    approved_list: list[ApprovedBinaryAsset] = []
    materialized_by_id: dict[str, MaterializedAsset] = {}
    with tempfile.TemporaryDirectory(prefix="migration-asset-runtime-") as tmp_raw:
        temp_dir = Path(tmp_raw)
        for item_id in sorted(assets_by_item):
            for asset in sorted(assets_by_item[item_id], key=lambda row: row.asset_id):
                approved = approved_by_asset_id.get(asset.asset_id)
                if approved is None:
                    raise MigrationAssetError(
                        f"Asset {asset.asset_id} ausente do approval bundle.",
                    )
                materialized = materialize_asset_readonly(
                    api_token,
                    asset,
                    downloader=downloader,
                    temp_dir=temp_dir,
                )
                if materialized.sha256 != approved.source_sha256:
                    raise MigrationAssetError(
                        f"SHA256 divergente asset {asset.asset_id}: "
                        f"runtime != approved.",
                    )
                materialized_by_id[asset.asset_id] = materialized
                approved_list.append(approved)
    return PreflightBatchResult(
        approved_assets=tuple(approved_list),
        materialized_by_asset_id=materialized_by_id,
    )


class WriteTracker(Protocol):
    storage_uploads: int
    attachment_link_writes: int


def assert_zero_external_writes(stats: WriteTracker) -> None:
    if stats.storage_uploads or stats.attachment_link_writes:
        raise MigrationAssetError(
            "Writes externos detectados após falha de SHA256 preflight.",
        )
