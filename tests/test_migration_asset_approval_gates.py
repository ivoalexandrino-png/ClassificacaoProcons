"""Testes de approval SHA256, preflight pre-write e Drive URL/permissões."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from classificacao_procons.migration.asset_attachment import plan_sunday_attachment
from classificacao_procons.migration.asset_models import (
    ApprovedBinaryAsset,
    MaterializedAsset,
    MigrationAssetError,
    MondayAssetMetadata,
    StorageObjectRecord,
)
from classificacao_procons.migration.asset_pipeline import (
    BinaryAssetApplyStats,
    apply_binary_batch_with_approval,
    apply_item_assets_with_approval,
    attachment_payload_digest,
)
from classificacao_procons.migration.asset_preflight import (
    approved_binary_asset_from_materialized,
    build_final_approval_assets,
    runtime_preflight_verify_batch,
)
from classificacao_procons.migration.asset_storage import (
    StorageBackendConfig,
    StoragePort,
    build_drive_stable_view_url,
    inspect_migration_assets_folder_policy,
    validate_stable_drive_public_url,
)
from classificacao_procons.migration.monday_asset_download import sanitize_asset_filename
from classificacao_procons.migration.operation_manifest import (
    ManifestOperation,
    migration_code_revision,
    operation_manifest_hash_v2,
)

BOARD = "4944254220"
SUNDAY = "82"
ITEM_A = "10736174113"
ITEM_B = "11304091950"
ASSET_PDF = "9001"
ASSET_JPG = "9002"
PREV_REVISION = "9b7a0e835e80bc6665dcf8e3"


def _asset(
    item_id: str,
    asset_id: str,
    *,
    name: str = "doc.pdf",
    size: int = 100,
    extension: str = "pdf",
) -> MondayAssetMetadata:
    return MondayAssetMetadata(
        board_id=BOARD,
        item_id=item_id,
        asset_id=asset_id,
        name=name,
        file_size=size,
        file_extension=extension,
        created_at="2026-08-18T00:00:00Z",
    )


def _materialized(asset: MondayAssetMetadata, content: bytes | None = None) -> MaterializedAsset:
    payload = content if content is not None else (b"x" * asset.file_size)
    ext = (asset.file_extension or "pdf").lstrip(".")
    return MaterializedAsset(
        metadata=asset,
        content=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        mime_type="application/pdf" if ext == "pdf" else "image/jpeg",
        sanitized_filename=sanitize_asset_filename(
            asset.name,
            asset_id=asset.asset_id,
            extension=ext,
        ),
    )


def _approved(materialized: MaterializedAsset) -> ApprovedBinaryAsset:
    return approved_binary_asset_from_materialized(
        materialized=materialized,
        sunday_board_id=SUNDAY,
    )


class FakeStorage(StoragePort):
    def __init__(self) -> None:
        self.uploads = 0
        self.adopts = 0

    def resolve(self, storage_key: str) -> StorageObjectRecord | None:
        return None

    def upload(self, *, storage_key: str, materialized: MaterializedAsset) -> StorageObjectRecord:
        self.uploads += 1
        file_id = f"file-{self.uploads}"
        return StorageObjectRecord(
            storage_key=storage_key,
            drive_file_id=file_id,
            public_url=build_drive_stable_view_url(file_id),
            sha256=materialized.sha256,
            size=len(materialized.content),
            mime_type=materialized.mime_type,
            original_filename=materialized.sanitized_filename,
            action="UPLOAD_REQUIRED",
        )


class FakeSunday:
    def __init__(self) -> None:
        self.created = 0
        self.attachments: dict[str, list] = {}

    def list_attachments(self, item_id: str):
        return list(self.attachments.get(item_id, []))

    def add_link_attachment(self, item_id: str, url: str, *, filename: str | None = None):
        self.created += 1
        attachment = MagicMock(id=str(self.created), url=url, filename=filename)
        self.attachments.setdefault(item_id, []).append(attachment)
        return attachment


def test_final_approval_manifest_includes_source_sha256():
    asset = _asset(ITEM_A, ASSET_PDF)
    materialized = _materialized(asset, b"%PDF-test-bytes")
    approved = _approved(materialized)
    digest = attachment_payload_digest(approved)
    assert digest != attachment_payload_digest(replace(approved, source_sha256="0" * 64))


def test_manifest_changes_when_sha_changes_with_same_metadata():
    meta = _asset(ITEM_A, ASSET_PDF, size=100)
    m1 = _materialized(meta, b"a" * 100)
    m2 = _materialized(meta, b"b" * 100)
    assert attachment_payload_digest(_approved(m1)) != attachment_payload_digest(_approved(m2))


def test_metadata_same_size_different_bytes_sha_mismatch_at_preflight():
    meta = _asset(ITEM_A, ASSET_PDF, size=20)
    runtime = _materialized(meta, b"runtime-bytes-000000")
    wrong_approved = replace(_approved(runtime), source_sha256="f" * 64)
    with pytest.raises(MigrationAssetError, match="SHA256 divergente"):
        runtime_preflight_verify_batch(
            "token",
            assets_by_item={ITEM_A: (meta,)},
            approved_by_asset_id={ASSET_PDF: wrong_approved},
            downloader=lambda _t, _a: runtime,
        )


def test_runtime_sha_mismatch_zero_external_writes():
    meta = _asset(ITEM_A, ASSET_PDF)
    runtime = _materialized(meta)
    wrong_approved = replace(_approved(runtime), source_sha256="0" * 64)
    storage = FakeStorage()
    sunday = FakeSunday()
    stats = BinaryAssetApplyStats()
    with pytest.raises(MigrationAssetError, match="SHA256 divergente"):
        apply_item_assets_with_approval(
            api_token="token",
            sunday_client=sunday,
            sunday_item_id="999",
            expected_assets=(meta,),
            approved_by_asset_id={ASSET_PDF: wrong_approved},
            storage=storage,
            stats=stats,
            downloader=lambda _t, _a: runtime,
        )
    assert storage.uploads == 0
    assert sunday.created == 0
    assert stats.storage_uploads == 0
    assert stats.attachment_link_writes == 0


def test_batch_preflights_all_assets_before_first_write():
    pdf_meta = _asset(ITEM_A, ASSET_PDF)
    jpg_meta = _asset(ITEM_B, ASSET_JPG, name="a.jpg", extension="jpg", size=50)
    jpg_meta2 = replace(jpg_meta, asset_id="9003")
    assets_by_item = {
        ITEM_A: (pdf_meta,),
        ITEM_B: (jpg_meta, jpg_meta2),
    }
    pdf_m = _materialized(pdf_meta, b"p" * 100)
    jpg_m = _materialized(jpg_meta, b"j" * 50)
    jpg_m2 = _materialized(jpg_meta2, b"k" * 50)
    approved = {
        ASSET_PDF: _approved(pdf_m),
        ASSET_JPG: _approved(jpg_m),
        "9003": _approved(jpg_m2),
    }

    call_log: list[str] = []

    def tracking_downloader(_token, asset):
        call_log.append(f"download:{asset.asset_id}")
        return {
            ASSET_PDF: pdf_m,
            ASSET_JPG: jpg_m,
            "9003": jpg_m2,
        }[asset.asset_id]

    storage = FakeStorage()
    original_upload = storage.upload

    def tracking_upload(**kwargs):
        call_log.append("storage_upload")
        return original_upload(**kwargs)

    storage.upload = tracking_upload  # type: ignore[method-assign]
    sunday = FakeSunday()
    original_add = sunday.add_link_attachment

    def tracking_add(*args, **kwargs):
        call_log.append("sunday_attachment")
        return original_add(*args, **kwargs)

    sunday.add_link_attachment = tracking_add  # type: ignore[method-assign]

    apply_binary_batch_with_approval(
        api_token="token",
        sunday_client=sunday,
        assets_by_item=assets_by_item,
        sunday_item_id_by_monday_item={ITEM_A: "111", ITEM_B: "222"},
        approved_by_asset_id=approved,
        storage=storage,
        downloader=tracking_downloader,
    )
    download_steps = [step for step in call_log if step.startswith("download:")]
    first_storage = next(i for i, step in enumerate(call_log) if step == "storage_upload")
    assert len(download_steps) == 3
    assert all(call_log.index(step) < first_storage for step in download_steps)


def test_build_final_approval_assets_read_only_no_storage():
    meta = _asset(ITEM_A, ASSET_PDF)
    materialized = _materialized(meta)

    with patch(
        "classificacao_procons.migration.asset_storage.DriveStorageBackend.upload",
        side_effect=AssertionError("Drive upload during final PLAN"),
    ):
        result = build_final_approval_assets(
            "token",
            assets_by_item={ITEM_A: (meta,)},
            sunday_board_id=SUNDAY,
            downloader=lambda _t, _a: materialized,
        )
    assert result.approved_assets[0].source_sha256 == materialized.sha256


def test_drive_stable_url_has_no_token():
    url = build_drive_stable_view_url("AbCdE12345")
    assert url == "https://drive.google.com/file/d/AbCdE12345/view"
    validate_stable_drive_public_url(url, file_id="AbCdE12345")
    with pytest.raises(MigrationAssetError, match="credencial temporária"):
        validate_stable_drive_public_url(
            "https://drive.google.com/uc?export=download&id=x&access_token=secret",
            file_id="x",
        )


def test_sunday_plan_rejects_non_stable_drive_url():
    meta = _asset(ITEM_A, ASSET_PDF)
    storage_record = StorageObjectRecord(
        storage_key="k",
        drive_file_id="1",
        public_url="https://drive.google.com/uc?export=download&id=1&access_token=x",
        sha256="abc",
        size=10,
        mime_type="application/pdf",
        original_filename="doc.pdf",
        action="UPLOAD_REQUIRED",
    )
    with pytest.raises(MigrationAssetError, match="credencial temporária"):
        plan_sunday_attachment(asset=meta, storage=storage_record)


def test_drive_upload_does_not_set_public_permissions():
    from pathlib import Path

    source = Path(__file__).resolve().parents[1].joinpath(
        "src/classificacao_procons/migration/asset_storage.py",
    ).read_text()
    assert "permissions().create" not in source
    assert "anyoneWithLink" not in source


def test_inspect_folder_policy_upload_does_not_alter_sharing():
    mock_service = MagicMock()
    mock_service.files().get().execute.return_value = {
        "id": "folder1",
        "name": "MigrationAssets",
        "driveId": "shared-drive-1",
        "shared": True,
    }
    mock_service.permissions().list().execute.return_value = {
        "permissions": [{"type": "user", "role": "writer", "deleted": False}],
    }
    with patch(
        "classificacao_procons.migration.asset_storage._build_drive_service",
        return_value=mock_service,
    ):
        report = inspect_migration_assets_folder_policy(
            StorageBackendConfig(root_folder_id="folder1"),
        )
    assert report.upload_alters_sharing is False
    assert report.public_exposure is False
    assert report.link_access_validated is False
    mock_service.permissions().create.assert_not_called()


def test_manifest_v2_changes_only_when_sha_changes():
    meta = _asset(ITEM_A, ASSET_PDF)
    m1 = _materialized(meta, b"same-meta-size-0000000000")
    m2 = _materialized(meta, b"different-bytes0000000")
    op1 = ManifestOperation(
        kind="ATTACHMENT",
        op_id=f"item:{ITEM_A}:asset:{ASSET_PDF}",
        monday_item_id=ITEM_A,
        payload_digest=attachment_payload_digest(_approved(m1)),
    )
    op2 = ManifestOperation(
        kind="ATTACHMENT",
        op_id=f"item:{ITEM_A}:asset:{ASSET_PDF}",
        monday_item_id=ITEM_A,
        payload_digest=attachment_payload_digest(_approved(m2)),
    )
    assert operation_manifest_hash_v2((op1,)) != operation_manifest_hash_v2((op2,))


def test_code_revision_changed_after_approval_gates():
    revision = migration_code_revision()
    assert revision != PREV_REVISION
