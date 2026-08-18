"""Gate APPLY binary contra approval bundle persistido."""

from __future__ import annotations

from dataclasses import dataclass

from classificacao_procons.migration.asset_models import (
    MaterializedAsset,
    MigrationAssetError,
    MondayAssetMetadata,
)
from classificacao_procons.migration.asset_preflight import runtime_preflight_verify_batch
from classificacao_procons.migration.binary_approval_bundle import (
    BinaryApprovalBundle,
    approved_assets_by_id,
    validate_budgets_exact,
    validate_expected_approval_digest,
    validate_item_scope_exact,
    validate_runtime_against_bundle,
)
from classificacao_procons.migration.operation_manifest import ScopedSafetyMetadata


@dataclass(frozen=True)
class BinaryApplyState:
    bundle: BinaryApprovalBundle
    assets_by_item: dict[str, tuple[MondayAssetMetadata, ...]]
    materialized_by_asset_id: dict[str, MaterializedAsset]
    api_token: str


def prepare_binary_apply_state(
    *,
    api_token: str,
    bundle: BinaryApprovalBundle,
    expected_digest: str,
    requested_item_ids: frozenset[str],
    current_scoped: ScopedSafetyMetadata,
    assets_by_item: dict[str, tuple[MondayAssetMetadata, ...]],
    max_items: int | None,
    max_assets: int | None,
    max_comments: int | None,
    max_storage_uploads: int | None,
    max_operations: int | None,
    downloader=None,
) -> BinaryApplyState:
    validate_expected_approval_digest(bundle, expected_digest)
    validate_item_scope_exact(bundle, requested_item_ids)
    validate_budgets_exact(
        bundle.budgets,
        max_items=max_items,
        max_assets=max_assets,
        max_comments=max_comments,
        max_storage_uploads=max_storage_uploads,
        max_operations=max_operations,
    )
    failures = validate_runtime_against_bundle(bundle, current_scoped)
    if failures:
        raise MigrationAssetError(
            "Binary approval runtime drift: " + "; ".join(failures),
        )
    approved_by_id = approved_assets_by_id(bundle)
    batch = runtime_preflight_verify_batch(
        api_token,
        assets_by_item=assets_by_item,
        approved_by_asset_id=approved_by_id,
        downloader=downloader,
    )
    return BinaryApplyState(
        bundle=bundle,
        assets_by_item=assets_by_item,
        materialized_by_asset_id=batch.materialized_by_asset_id,
        api_token=api_token,
    )
