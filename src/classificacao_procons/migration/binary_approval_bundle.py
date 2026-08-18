"""Artifact canônico de approval humano para piloto binary (PLAN → APPLY)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from classificacao_procons.migration.asset_models import ApprovedBinaryAsset, MigrationAssetError
from classificacao_procons.migration.operation_manifest import ScopedSafetyMetadata

BUNDLE_VERSION = "1"
APPROVAL_DIGEST_MISMATCH = "APPROVAL_BUNDLE_DIGEST_MISMATCH"


@dataclass(frozen=True)
class BinaryApprovalBudgets:
    max_items: int
    max_assets: int
    max_comments: int
    max_storage_uploads: int
    max_operations: int

    def as_dict(self) -> dict[str, int]:
        return {
            "max_items": self.max_items,
            "max_assets": self.max_assets,
            "max_comments": self.max_comments,
            "max_storage_uploads": self.max_storage_uploads,
            "max_operations": self.max_operations,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BinaryApprovalBudgets:
        return cls(
            max_items=int(payload["max_items"]),
            max_assets=int(payload["max_assets"]),
            max_comments=int(payload["max_comments"]),
            max_storage_uploads=int(payload["max_storage_uploads"]),
            max_operations=int(payload["max_operations"]),
        )


@dataclass(frozen=True)
class BinaryApprovalBundle:
    version: str
    board_id: str
    wave: int
    item_ids: tuple[str, ...]
    selected_source: str
    schema: str
    manifest_v2: str
    code_revision: str
    board_global: str
    operation_total: int
    budgets: BinaryApprovalBudgets
    approved_assets: tuple[ApprovedBinaryAsset, ...]

    @property
    def approval_bundle_digest(self) -> str:
        return compute_approval_bundle_digest(self)


def approved_asset_to_dict(asset: ApprovedBinaryAsset) -> dict[str, object]:
    return {
        "board_id": asset.board_id,
        "monday_item_id": asset.monday_item_id,
        "asset_id": asset.asset_id,
        "sanitized_filename": asset.sanitized_filename,
        "mime_type": asset.mime_type,
        "size": asset.size,
        "source_sha256": asset.source_sha256,
        "storage_object_key": asset.storage_object_key,
        "sunday_board_id": asset.sunday_board_id,
    }


def approved_asset_from_dict(payload: dict[str, Any]) -> ApprovedBinaryAsset:
    return ApprovedBinaryAsset(
        board_id=str(payload["board_id"]),
        monday_item_id=str(payload["monday_item_id"]),
        asset_id=str(payload["asset_id"]),
        sanitized_filename=str(payload["sanitized_filename"]),
        mime_type=str(payload["mime_type"]),
        size=int(payload["size"]),
        source_sha256=str(payload["source_sha256"]),
        storage_object_key=str(payload["storage_object_key"]),
        sunday_board_id=str(payload["sunday_board_id"]),
    )


def _sorted_assets(
    assets: tuple[ApprovedBinaryAsset, ...],
) -> tuple[ApprovedBinaryAsset, ...]:
    return tuple(sorted(assets, key=lambda row: (row.monday_item_id, row.asset_id)))


def bundle_to_canonical_dict(bundle: BinaryApprovalBundle) -> dict[str, object]:
    """JSON canônico para digest (sem campo approval_bundle_digest)."""
    return {
        "version": bundle.version,
        "board_id": bundle.board_id,
        "wave": bundle.wave,
        "item_ids": list(bundle.item_ids),
        "selected_source": bundle.selected_source,
        "schema": bundle.schema,
        "manifest_v2": bundle.manifest_v2,
        "code_revision": bundle.code_revision,
        "board_global": bundle.board_global,
        "operation_total": bundle.operation_total,
        "budgets": bundle.budgets.as_dict(),
        "approved_assets": [
            approved_asset_to_dict(asset)
            for asset in _sorted_assets(bundle.approved_assets)
        ],
    }


def compute_approval_bundle_digest(bundle: BinaryApprovalBundle) -> str:
    canonical = json.dumps(
        bundle_to_canonical_dict(bundle),
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def bundle_to_persisted_dict(bundle: BinaryApprovalBundle) -> dict[str, object]:
    payload = bundle_to_canonical_dict(bundle)
    payload["approval_bundle_digest"] = bundle.approval_bundle_digest
    return payload


def bundle_from_dict(payload: dict[str, Any]) -> BinaryApprovalBundle:
    assets = tuple(
        approved_asset_from_dict(row)
        for row in payload.get("approved_assets") or []
    )
    bundle = BinaryApprovalBundle(
        version=str(payload.get("version") or BUNDLE_VERSION),
        board_id=str(payload["board_id"]),
        wave=int(payload["wave"]),
        item_ids=tuple(sorted(str(item_id) for item_id in payload["item_ids"])),
        selected_source=str(payload["selected_source"]),
        schema=str(payload["schema"]),
        manifest_v2=str(payload["manifest_v2"]),
        code_revision=str(payload["code_revision"]),
        board_global=str(payload["board_global"]),
        operation_total=int(payload["operation_total"]),
        budgets=BinaryApprovalBudgets.from_dict(payload["budgets"]),
        approved_assets=_sorted_assets(assets),
    )
    stored_digest = str(payload.get("approval_bundle_digest") or "").strip()
    if stored_digest and stored_digest != bundle.approval_bundle_digest:
        raise MigrationAssetError(APPROVAL_DIGEST_MISMATCH)
    return bundle


def load_binary_approval_bundle(path: str | Path) -> BinaryApprovalBundle:
    raw = Path(path).read_text(encoding="utf-8")
    return bundle_from_dict(json.loads(raw))


def save_binary_approval_bundle(bundle: BinaryApprovalBundle, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(bundle_to_persisted_dict(bundle), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_binary_approval_bundle(
    *,
    board_id: str,
    wave: int,
    item_ids: frozenset[str] | set[str],
    scoped_safety: ScopedSafetyMetadata,
    approved_assets: tuple[ApprovedBinaryAsset, ...],
    budgets: BinaryApprovalBudgets,
) -> BinaryApprovalBundle:
    return BinaryApprovalBundle(
        version=BUNDLE_VERSION,
        board_id=board_id,
        wave=wave,
        item_ids=tuple(sorted(item_ids)),
        selected_source=scoped_safety.selected_source_fingerprint,
        schema=scoped_safety.migration_schema_fingerprint,
        manifest_v2=scoped_safety.operation_manifest_hash_v2,
        code_revision=scoped_safety.code_revision,
        board_global=scoped_safety.board_global_fingerprint,
        operation_total=scoped_safety.accounting.operation_total,
        budgets=budgets,
        approved_assets=_sorted_assets(approved_assets),
    )


def validate_expected_approval_digest(
    bundle: BinaryApprovalBundle,
    expected_digest: str,
) -> None:
    if bundle.approval_bundle_digest != expected_digest.strip():
        raise MigrationAssetError(APPROVAL_DIGEST_MISMATCH)


def validate_item_scope_exact(
    bundle: BinaryApprovalBundle,
    requested_item_ids: frozenset[str],
) -> None:
    if frozenset(bundle.item_ids) != requested_item_ids:
        raise MigrationAssetError(
            "ITEM_SCOPE_MISMATCH: item_ids do bundle divergem do --item-ids.",
        )


def validate_budgets_exact(
    bundle: BinaryApprovalBudgets,
    *,
    max_items: int | None,
    max_assets: int | None,
    max_comments: int | None,
    max_storage_uploads: int | None,
    max_operations: int | None,
) -> None:
    checks = {
        "max_items": max_items,
        "max_assets": max_assets,
        "max_comments": max_comments,
        "max_storage_uploads": max_storage_uploads,
        "max_operations": max_operations,
    }
    for field, actual in checks.items():
        if actual is None:
            continue
        expected = getattr(bundle, field)
        if actual != expected:
            raise MigrationAssetError(
                f"BUDGET_MISMATCH: {field} CLI={actual} != approval={expected}.",
            )


def validate_runtime_against_bundle(
    bundle: BinaryApprovalBundle,
    current: ScopedSafetyMetadata,
) -> list[str]:
    """Compara runtime fresh contra approval persistido (fail-closed)."""
    failures: list[str] = []
    if current.selected_source_fingerprint != bundle.selected_source:
        failures.append("selected_source divergente")
    if current.migration_schema_fingerprint != bundle.schema:
        failures.append("schema divergente")
    if current.operation_manifest_hash_v2 != bundle.manifest_v2:
        failures.append("manifest_v2 divergente")
    if current.code_revision != bundle.code_revision:
        failures.append("code_revision divergente")
    if current.accounting.operation_total != bundle.operation_total:
        failures.append("operation_total divergente")
    return failures


def approved_assets_by_id(bundle: BinaryApprovalBundle) -> dict[str, ApprovedBinaryAsset]:
    return {asset.asset_id: asset for asset in bundle.approved_assets}


def plan_requires_binary_approval(
    *,
    max_assets: int | None,
    max_storage_uploads: int | None,
) -> bool:
    return bool(max_assets and max_assets > 0) or bool(
        max_storage_uploads and max_storage_uploads > 0,
    )


def group_approved_assets_by_item(
    assets: tuple[ApprovedBinaryAsset, ...],
) -> dict[str, tuple[ApprovedBinaryAsset, ...]]:
    grouped: dict[str, list[ApprovedBinaryAsset]] = {}
    for asset in assets:
        grouped.setdefault(asset.monday_item_id, []).append(asset)
    return {
        item_id: tuple(sorted(rows, key=lambda row: row.asset_id))
        for item_id, rows in grouped.items()
    }


def generate_binary_approval_artifact(
    *,
    api_token: str,
    board_id: str,
    sunday_board_id: str,
    wave: int,
    item_ids: frozenset[str],
    inventory,
    board_plan,
    sunday_snapshot,
    apply_sources,
    plan_operations,
    monday_id_column_id: str,
    budgets: BinaryApprovalBudgets,
    downloader=None,
) -> tuple[BinaryApprovalBundle, object]:
    from classificacao_procons.migration.asset_preflight import build_final_approval_assets
    from classificacao_procons.migration.monday_asset_metadata import fetch_item_assets_metadata
    from classificacao_procons.migration.operation_manifest import attach_scoped_safety_metadata

    assets_meta = fetch_item_assets_metadata(
        api_token,
        board_id=board_id,
        item_ids=item_ids,
    )
    preflight = build_final_approval_assets(
        api_token,
        assets_by_item=assets_meta,
        sunday_board_id=sunday_board_id,
        downloader=downloader,
    )
    approved_by_item = group_approved_assets_by_item(preflight.approved_assets)
    scoped = attach_scoped_safety_metadata(
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources=apply_sources,
        plan_operations=plan_operations,
        selected_item_ids=item_ids,
        monday_id_column_id=monday_id_column_id,
        monday_board_id=board_id,
        assets_by_item=approved_by_item,
        metadata_assets_by_item=assets_meta,
    )
    bundle = build_binary_approval_bundle(
        board_id=board_id,
        wave=wave,
        item_ids=item_ids,
        scoped_safety=scoped,
        approved_assets=preflight.approved_assets,
        budgets=budgets,
    )
    return bundle, scoped
