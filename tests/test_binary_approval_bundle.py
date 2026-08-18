"""Testes do artifact canônico BinaryApprovalBundle e gate APPLY binary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from classificacao_procons.migration.asset_models import (
    ApprovedBinaryAsset,
    MigrationAssetError,
    MondayAssetMetadata,
)
from classificacao_procons.migration.asset_preflight import approved_binary_asset_from_materialized
from classificacao_procons.migration.binary_apply import prepare_binary_apply_state
from classificacao_procons.migration.binary_approval_bundle import (
    APPROVAL_DIGEST_MISMATCH,
    BinaryApprovalBudgets,
    BinaryApprovalBundle,
    build_binary_approval_bundle,
    bundle_to_persisted_dict,
    compute_approval_bundle_digest,
    load_binary_approval_bundle,
    save_binary_approval_bundle,
    validate_expected_approval_digest,
    validate_item_scope_exact,
    validate_runtime_against_bundle,
)
from classificacao_procons.migration.monday_asset_download import (
    MONDAY_FILES_API,
    build_download_request,
    classify_download_auth_mode,
    resolve_download_target,
    sanitize_asset_filename,
)
from classificacao_procons.migration.operation_manifest import (
    OperationAccounting,
    ScopedSafetyMetadata,
    migration_code_revision,
)

BOARD = "4944254220"
SUNDAY = "82"
ITEM_A = "10736174113"
ITEM_B = "11304091950"
ASSET_PDF = "9001"
ASSET_JPG = "9002"
ASSET_JPG2 = "9003"
ASSET_JPG3 = "9004"
ASSET_JPG4 = "9005"
PRIOR_CODE_REVISION = "72bbbdcaeb5a67b6c59f8369"


def _accounting(**overrides) -> OperationAccounting:
    defaults = dict(
        item_creates=2,
        system_writes=4,
        custom_other_writes=10,
        status_writes=2,
        link_writes=4,
        comments=8,
        attachments=5,
        relations=0,
        subitems=0,
        ledger_operations=2,
        asset_downloads=5,
        storage_uploads=5,
        attachment_link_writes=5,
    )
    defaults.update(overrides)
    return OperationAccounting(**defaults)


def _scoped(**overrides) -> ScopedSafetyMetadata:
    accounting = overrides.pop("accounting", _accounting())
    defaults = dict(
        board_global_fingerprint="fe066a9545356b9de450cacf",
        board_source_total=100,
        selected_item_ids=(ITEM_A, ITEM_B),
        selected_source_fingerprint="d409bc5f90ff0897422a5c58",
        migration_schema_fingerprint="0b08b2a7267e882bb3f28900",
        operation_manifest_hash_v2="0b59491017f7b33245281bae",
        code_revision=migration_code_revision(),
        accounting=accounting,
    )
    defaults.update(overrides)
    return ScopedSafetyMetadata(**defaults)


def _approved(
    item_id: str,
    asset_id: str,
    *,
    name: str = "doc.pdf",
    size: int = 100,
    extension: str = "pdf",
    content: bytes | None = None,
    storage_key: str | None = None,
) -> ApprovedBinaryAsset:
    payload = content if content is not None else (b"x" * size)
    meta = MondayAssetMetadata(
        board_id=BOARD,
        item_id=item_id,
        asset_id=asset_id,
        name=name,
        file_size=size,
        file_extension=extension,
        created_at="2026-08-18T00:00:00Z",
    )
    from classificacao_procons.migration.asset_models import MaterializedAsset

    materialized = MaterializedAsset(
        metadata=meta,
        content=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        mime_type="application/pdf" if extension == "pdf" else "image/jpeg",
        sanitized_filename=sanitize_asset_filename(
            name,
            asset_id=asset_id,
            extension=extension,
        ),
    )
    approved = approved_binary_asset_from_materialized(
        materialized=materialized,
        sunday_board_id=SUNDAY,
    )
    if storage_key is not None:
        approved = replace(approved, storage_object_key=storage_key)
    return approved


def _budgets(**overrides) -> BinaryApprovalBudgets:
    defaults = dict(
        max_items=2,
        max_assets=5,
        max_comments=8,
        max_storage_uploads=5,
        max_operations=75,
    )
    defaults.update(overrides)
    return BinaryApprovalBudgets(**defaults)


def _sample_bundle(
    *,
    assets: tuple[ApprovedBinaryAsset, ...] | None = None,
    scoped: ScopedSafetyMetadata | None = None,
    budgets: BinaryApprovalBudgets | None = None,
) -> BinaryApprovalBundle:
    scoped = scoped or _scoped()
    assets = assets or (
        _approved(ITEM_A, ASSET_PDF),
        _approved(ITEM_B, ASSET_JPG, name="a.jpg", size=50, extension="jpg"),
    )
    return build_binary_approval_bundle(
        board_id=BOARD,
        wave=1,
        item_ids=frozenset({ITEM_A, ITEM_B}),
        scoped_safety=scoped,
        approved_assets=assets,
        budgets=budgets or _budgets(),
    )


def test_bundle_round_trip_preserves_full_sha256(tmp_path: Path):
    bundle = _sample_bundle()
    path = tmp_path / "approval.json"
    save_binary_approval_bundle(bundle, path)
    loaded = load_binary_approval_bundle(path)
    assert loaded.approved_assets[0].source_sha256 == bundle.approved_assets[0].source_sha256
    assert len(loaded.approved_assets[0].source_sha256) == 64
    assert loaded.approval_bundle_digest == bundle.approval_bundle_digest


def test_process_restart_simulation(tmp_path: Path):
    bundle = _sample_bundle()
    path = tmp_path / "approvals" / "pilot.json"
    save_binary_approval_bundle(bundle, path)
    digest = bundle.approval_bundle_digest

    def process_b_load():
        reloaded = load_binary_approval_bundle(path)
        validate_expected_approval_digest(reloaded, digest)
        return reloaded

    loaded = process_b_load()
    assert loaded.approved_assets == bundle.approved_assets


def test_canonical_digest_is_deterministic():
    bundle = _sample_bundle()
    digest_a = compute_approval_bundle_digest(bundle)
    digest_b = compute_approval_bundle_digest(bundle)
    assert digest_a == digest_b
    assert len(digest_a) == 64


def test_dict_key_order_does_not_change_digest():
    bundle = _sample_bundle()
    canonical = json.dumps(
        bundle_to_persisted_dict(bundle),
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    shuffled = json.dumps(
        json.loads(canonical),
        sort_keys=False,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    assert hashlib.sha256(canonical.encode()).hexdigest() == hashlib.sha256(
        json.dumps(json.loads(shuffled), sort_keys=True, separators=(",", ":")).encode(),
    ).hexdigest()


def test_asset_list_order_does_not_change_digest():
    a1 = _approved(ITEM_A, ASSET_PDF)
    a2 = _approved(ITEM_B, ASSET_JPG, name="a.jpg", size=50, extension="jpg")
    bundle_forward = _sample_bundle(assets=(a1, a2))
    bundle_reverse = _sample_bundle(assets=(a2, a1))
    assert bundle_forward.approval_bundle_digest == bundle_reverse.approval_bundle_digest


def _mutate_add_asset(bundle: BinaryApprovalBundle) -> BinaryApprovalBundle:
    extra = _approved(ITEM_B, "9999", name="z.jpg", size=1, extension="jpg")
    return replace(bundle, approved_assets=bundle.approved_assets + (extra,))


def _mutate_remove_asset(bundle: BinaryApprovalBundle) -> BinaryApprovalBundle:
    kept = tuple(a for a in bundle.approved_assets if a.asset_id != ASSET_JPG)
    return replace(bundle, approved_assets=kept)


def _mutate_asset_field(bundle: BinaryApprovalBundle, **changes) -> BinaryApprovalBundle:
    updated = []
    for asset in bundle.approved_assets:
        if asset.asset_id == ASSET_PDF:
            updated.append(replace(asset, **changes))
        else:
            updated.append(asset)
    return replace(bundle, approved_assets=tuple(updated))


@pytest.mark.parametrize(
    ("mutator", "label"),
    [
        (_mutate_add_asset, "asset_added"),
        (_mutate_remove_asset, "asset_removed"),
        (lambda b: _mutate_asset_field(b, source_sha256="f" * 64), "sha_changed"),
        (lambda b: _mutate_asset_field(b, size=999), "size_changed"),
        (lambda b: _mutate_asset_field(b, storage_object_key="other/key"), "storage_key_changed"),
        (lambda b: replace(b, selected_source="0" * 24), "selected_source_changed"),
        (lambda b: replace(b, schema="1" * 24), "schema_changed"),
        (lambda b: replace(b, manifest_v2="2" * 24), "manifest_changed"),
        (lambda b: replace(b, code_revision="3" * 24), "code_revision_changed"),
        (lambda b: replace(b, operation_total=999), "operation_total_changed"),
        (lambda b: replace(b, budgets=replace(b.budgets, max_assets=99)), "budget_changed"),
    ],
)
def test_digest_changes_on_authorized_field_mutation(mutator, label):
    original = _sample_bundle()
    original_digest = original.approval_bundle_digest
    mutated = mutator(original)
    assert mutated.approval_bundle_digest != original_digest, label


def test_tamper_source_sha256_without_expected_digest_mismatch(tmp_path: Path):
    bundle = _sample_bundle()
    path = tmp_path / "tampered.json"
    save_binary_approval_bundle(bundle, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["approved_assets"][0]["source_sha256"] = "a" * 64
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(MigrationAssetError, match=APPROVAL_DIGEST_MISMATCH):
        load_binary_approval_bundle(path)


@pytest.mark.parametrize("field", ["asset_id", "size", "storage_object_key"])
def test_tamper_fields_raise_digest_mismatch(tmp_path: Path, field: str):
    bundle = _sample_bundle()
    path = tmp_path / f"tamper-{field}.json"
    save_binary_approval_bundle(bundle, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if field == "size":
        payload["approved_assets"][0][field] = 99999
    elif field == "asset_id":
        payload["approved_assets"][0][field] = "tampered"
    else:
        payload["approved_assets"][0][field] = "tampered/key"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(MigrationAssetError, match=APPROVAL_DIGEST_MISMATCH):
        load_binary_approval_bundle(path)


def test_validate_expected_approval_digest_mismatch():
    bundle = _sample_bundle()
    with pytest.raises(MigrationAssetError, match=APPROVAL_DIGEST_MISMATCH):
        validate_expected_approval_digest(bundle, "0" * 64)


def test_item_scope_exact_mismatch():
    bundle = _sample_bundle()
    with pytest.raises(MigrationAssetError, match="ITEM_SCOPE_MISMATCH"):
        validate_item_scope_exact(bundle, frozenset({ITEM_A}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selected_source_fingerprint", "deadbeef" * 3),
        ("migration_schema_fingerprint", "cafebabe" * 3),
        ("operation_manifest_hash_v2", "feedface" * 3),
        ("code_revision", "baadf00d" * 3),
    ],
)
def test_runtime_drift_detected(field: str, value: str):
    bundle = _sample_bundle()
    scoped = _scoped(**{field: value})
    failures = validate_runtime_against_bundle(bundle, scoped)
    assert failures


def test_runtime_operation_total_drift():
    bundle = _sample_bundle()
    scoped = _scoped(accounting=_accounting(storage_uploads=99))
    failures = validate_runtime_against_bundle(bundle, scoped)
    assert any("operation_total" in failure for failure in failures)


def _meta(item_id: str, asset_id: str, *, size: int = 100) -> MondayAssetMetadata:
    return MondayAssetMetadata(
        board_id=BOARD,
        item_id=item_id,
        asset_id=asset_id,
        name="doc.pdf",
        file_size=size,
        file_extension="pdf",
        created_at="2026-08-18T00:00:00Z",
    )


def _downloader_factory(materialized_by_id: dict):
    def downloader(_token, asset):

        return materialized_by_id[asset.asset_id]

    return downloader


def test_prepare_binary_apply_state_sha_mismatch_zero_writes():
    bundle = _sample_bundle()
    meta_a = _meta(ITEM_A, ASSET_PDF)
    meta_b = _meta(ITEM_B, ASSET_JPG, size=50)
    from classificacao_procons.migration.asset_models import MaterializedAsset

    runtime_a = MaterializedAsset(
        metadata=meta_a,
        content=b"a" * 100,
        sha256=hashlib.sha256(b"a" * 100).hexdigest(),
        mime_type="application/pdf",
        sanitized_filename="doc.pdf",
    )
    runtime_b = MaterializedAsset(
        metadata=meta_b,
        content=b"y" * 50,
        sha256=hashlib.sha256(b"y" * 50).hexdigest(),
        mime_type="image/jpeg",
        sanitized_filename="a.jpg",
    )
    with pytest.raises(MigrationAssetError, match="SHA256 divergente"):
        prepare_binary_apply_state(
            api_token="token",
            bundle=bundle,
            expected_digest=bundle.approval_bundle_digest,
            requested_item_ids=frozenset({ITEM_A, ITEM_B}),
            current_scoped=_scoped(),
            assets_by_item={ITEM_A: (meta_a,), ITEM_B: (meta_b,)},
            max_items=2,
            max_assets=5,
            max_comments=8,
            max_storage_uploads=5,
            max_operations=75,
            downloader=_downloader_factory({ASSET_PDF: runtime_a, ASSET_JPG: runtime_b}),
        )


def test_last_asset_mismatch_aborts_entire_batch():
    assets = (
        _approved(ITEM_A, ASSET_PDF),
        _approved(ITEM_B, ASSET_JPG, name="a.jpg", size=50, extension="jpg"),
        _approved(ITEM_B, ASSET_JPG2, name="b.jpg", size=51, extension="jpg"),
        _approved(ITEM_B, ASSET_JPG3, name="c.jpg", size=52, extension="jpg"),
        _approved(ITEM_B, ASSET_JPG4, name="d.jpg", size=53, extension="jpg"),
    )
    bundle = _sample_bundle(assets=assets)
    assets_by_item = {
        ITEM_A: (_meta(ITEM_A, ASSET_PDF),),
        ITEM_B: (
            _meta(ITEM_B, ASSET_JPG, size=50),
            _meta(ITEM_B, ASSET_JPG2, size=51),
            _meta(ITEM_B, ASSET_JPG3, size=52),
            _meta(ITEM_B, ASSET_JPG4, size=53),
        ),
    }
    materialized = {}
    for asset in assets:
        from classificacao_procons.migration.asset_models import MaterializedAsset

        item_assets = assets_by_item[asset.monday_item_id]
        meta = next(m for m in item_assets if m.asset_id == asset.asset_id)
        content = b"x" * asset.size
        if asset.asset_id == ASSET_JPG4:
            content = (b"z" * (asset.size - 1)) + b"w"
        materialized[asset.asset_id] = MaterializedAsset(
            metadata=meta,
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            mime_type=asset.mime_type,
            sanitized_filename=asset.sanitized_filename,
        )
    with pytest.raises(MigrationAssetError, match="SHA256 divergente"):
        prepare_binary_apply_state(
            api_token="token",
            bundle=bundle,
            expected_digest=bundle.approval_bundle_digest,
            requested_item_ids=frozenset({ITEM_A, ITEM_B}),
            current_scoped=_scoped(),
            assets_by_item=assets_by_item,
            max_items=2,
            max_assets=5,
            max_comments=8,
            max_storage_uploads=5,
            max_operations=75,
            downloader=_downloader_factory(materialized),
        )


def test_process_restart_end_to_end_mock(tmp_path: Path):
    bundle = _sample_bundle()
    path = tmp_path / "restart.json"
    save_binary_approval_bundle(bundle, path)
    digest = bundle.approval_bundle_digest

    # PROCESS A ends; PROCESS B starts
    loaded = load_binary_approval_bundle(path)
    meta_a = _meta(ITEM_A, ASSET_PDF)
    meta_b = _meta(ITEM_B, ASSET_JPG, size=50)
    from classificacao_procons.migration.asset_models import MaterializedAsset

    mat_a = MaterializedAsset(
        metadata=meta_a,
        content=b"x" * 100,
        sha256=hashlib.sha256(b"x" * 100).hexdigest(),
        mime_type="application/pdf",
        sanitized_filename="doc.pdf",
    )
    mat_b = MaterializedAsset(
        metadata=meta_b,
        content=b"x" * 50,
        sha256=hashlib.sha256(b"x" * 50).hexdigest(),
        mime_type="image/jpeg",
        sanitized_filename="a.jpg",
    )
    state = prepare_binary_apply_state(
        api_token="token",
        bundle=loaded,
        expected_digest=digest,
        requested_item_ids=frozenset({ITEM_A, ITEM_B}),
        current_scoped=_scoped(),
        assets_by_item={ITEM_A: (meta_a,), ITEM_B: (meta_b,)},
        max_items=2,
        max_assets=5,
        max_comments=8,
        max_storage_uploads=5,
        max_operations=75,
        downloader=_downloader_factory({ASSET_PDF: mat_a, ASSET_JPG: mat_b}),
    )
    assert state.bundle.approved_assets[0].source_sha256 == bundle.approved_assets[0].source_sha256


def test_cli_defines_binary_approval_flags():
    script = Path(__file__).resolve().parents[1] / "scripts" / "sunday_migration_execute.py"
    source = script.read_text(encoding="utf-8")
    assert "--approval-bundle-out" in source
    assert "--approval-bundle" in source
    assert "--expected-approval-digest" in source
    assert "prepare_binary_apply_state" in source


def test_missing_expected_digest_aborts_before_preflight():
    bundle = _sample_bundle()
    with pytest.raises(MigrationAssetError, match=APPROVAL_DIGEST_MISMATCH):
        prepare_binary_apply_state(
            api_token="token",
            bundle=bundle,
            expected_digest="0" * 64,
            requested_item_ids=frozenset({ITEM_A, ITEM_B}),
            current_scoped=_scoped(),
            assets_by_item={},
            max_items=2,
            max_assets=5,
            max_comments=8,
            max_storage_uploads=5,
            max_operations=75,
        )


def test_budget_mismatch_aborts_before_preflight():
    bundle = _sample_bundle()
    with pytest.raises(MigrationAssetError, match="BUDGET_MISMATCH"):
        prepare_binary_apply_state(
            api_token="token",
            bundle=bundle,
            expected_digest=bundle.approval_bundle_digest,
            requested_item_ids=frozenset({ITEM_A, ITEM_B}),
            current_scoped=_scoped(),
            assets_by_item={},
            max_items=2,
            max_assets=99,
            max_comments=8,
            max_storage_uploads=5,
            max_operations=75,
        )


def test_plan_requires_binary_approval_gate():
    from classificacao_procons.migration.binary_approval_bundle import plan_requires_binary_approval

    assert plan_requires_binary_approval(max_assets=5, max_storage_uploads=None) is True
    assert plan_requires_binary_approval(max_assets=None, max_storage_uploads=3) is True
    assert plan_requires_binary_approval(max_assets=0, max_storage_uploads=0) is False


def test_classify_download_auth_mode_s3_is_presigned():
    url = "https://files-monday-com.s3.amazonaws.com/bucket/key?X-Amz-Signature=abc"
    assert classify_download_auth_mode(url) == "presigned"


def test_classify_download_auth_mode_monday_api():
    url = f"{MONDAY_FILES_API}/12345"
    assert classify_download_auth_mode(url) == "monday_auth"


def test_build_download_request_presigned_omits_authorization():
    from classificacao_procons.migration.monday_asset_download import DownloadTarget

    request = build_download_request(
        DownloadTarget(
            url="https://files-monday-com.s3.amazonaws.com/x?sig=1",
            auth_mode="presigned",
        ),
        "secret-token",
    )
    assert "Authorization" not in request.headers


def test_build_download_request_monday_api_includes_authorization():
    from classificacao_procons.migration.monday_asset_download import DownloadTarget

    request = build_download_request(
        DownloadTarget(url=f"{MONDAY_FILES_API}/1", auth_mode="monday_auth"),
        "secret-token",
    )
    assert request.headers.get("Authorization") == "secret-token"


def test_resolve_download_target_prefers_public_url(monkeypatch):
    asset = _meta(ITEM_A, ASSET_PDF)

    def fake_graphql(**_kwargs):
        return {
            "assets": [
                {
                    "id": ASSET_PDF,
                    "url": "https://monday.com/files/1",
                    "public_url": "https://files-monday-com.s3.amazonaws.com/f/key",
                },
            ],
        }

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_asset_download._graphql_request",
        lambda **_k: fake_graphql(),
    )
    target = resolve_download_target("token", asset)
    assert target.auth_mode == "presigned"
    assert "s3" in target.url


def test_migration_code_revision_changed_from_prior_pilot():
    revision = migration_code_revision()
    assert revision != PRIOR_CODE_REVISION
    assert len(revision) == 24
