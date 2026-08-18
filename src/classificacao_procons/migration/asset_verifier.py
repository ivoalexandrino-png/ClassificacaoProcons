"""Verifier canônico para item.assets materializados."""

from __future__ import annotations

from dataclasses import dataclass, field

from classificacao_procons.migration.asset_attachment import (
    asset_attachment_marker,
)
from classificacao_procons.migration.asset_models import (
    AssetVerifyResult,
    MondayAssetMetadata,
)
from classificacao_procons.migration.asset_storage import StoragePort


@dataclass
class AssetVerificationRow:
    asset_id: str
    result: AssetVerifyResult
    detail: str = ""


@dataclass
class AssetVerificationReport:
    rows: list[AssetVerificationRow] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(row.result == "MATCH" for row in self.rows)


def verify_materialized_asset(
    *,
    expected: MondayAssetMetadata,
    materialized_sha256: str,
    materialized_size: int,
    storage: StoragePort,
    storage_key: str,
    sunday_attachments,
) -> AssetVerificationRow:
    marker = asset_attachment_marker(
        board_id=expected.board_id,
        item_id=expected.item_id,
        asset_id=expected.asset_id,
    )
    stored = storage.resolve(storage_key)
    if stored is None:
        return AssetVerificationRow(
            asset_id=expected.asset_id,
            result="MISSING_STORAGE",
            detail="storage object ausente",
        )
    if stored.sha256 and stored.sha256 != materialized_sha256:
        return AssetVerificationRow(
            asset_id=expected.asset_id,
            result="STORAGE_HASH_MISMATCH",
            detail="sha256 diverge",
        )
    if stored.size and stored.size != materialized_size:
        return AssetVerificationRow(
            asset_id=expected.asset_id,
            result="STORAGE_HASH_MISMATCH",
            detail="size diverge",
        )

    matches = [
        attachment
        for attachment in sunday_attachments
        if attachment.filename and marker in attachment.filename
    ]
    if not matches:
        return AssetVerificationRow(
            asset_id=expected.asset_id,
            result="MISSING_SUNDAY_ATTACHMENT",
        )
    if len(matches) > 1:
        return AssetVerificationRow(
            asset_id=expected.asset_id,
            result="DUPLICATE_SUNDAY_ATTACHMENT",
        )
    return AssetVerificationRow(asset_id=expected.asset_id, result="MATCH")
