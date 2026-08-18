"""Testes do pipeline Monday item.assets → storage → Sunday attachment."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from classificacao_procons.migration.asset_attachment import (
    asset_attachment_marker,
    ensure_sunday_link_attachment,
    find_attachment_by_marker,
    plan_sunday_attachment,
)
from classificacao_procons.migration.asset_models import (
    MaterializedAsset,
    MigrationAssetError,
    MondayAssetMetadata,
    StorageObjectRecord,
)
from classificacao_procons.migration.asset_pipeline import (
    BinaryAssetApplyStats,
    apply_item_assets,
    attachment_payload_digest,
    classify_binary_item_ready,
    validate_asset_extension,
)
from classificacao_procons.migration.asset_storage import (
    StoragePort,
    build_storage_object_key,
)
from classificacao_procons.migration.monday_asset_download import (
    download_monday_asset,
    materialized_matches_metadata,
    sanitize_asset_filename,
)
from classificacao_procons.migration.monday_asset_metadata import assets_fingerprint_basis
from classificacao_procons.migration.operation_manifest import (
    ManifestOperation,
    migration_code_revision,
    operation_manifest_hash_v2,
    summarize_manifest_accounting,
)
from classificacao_procons.sunday.models import Attachment

BOARD = "4944254220"
ITEM = "10736174113"
ASSET_A = "9001"
ASSET_B = "9002"
OLD_CODE_REVISION = "9d2b7264c10207bb09323dda"


def _asset(
    asset_id: str,
    *,
    name: str = "doc.pdf",
    size: int | None = 100,
    extension: str = "pdf",
) -> MondayAssetMetadata:
    return MondayAssetMetadata(
        board_id=BOARD,
        item_id=ITEM,
        asset_id=asset_id,
        name=name,
        file_size=size,
        file_extension=extension,
        created_at="2026-08-18T00:00:00Z",
    )


def _materialized(
    asset: MondayAssetMetadata,
    content: bytes | None = None,
) -> MaterializedAsset:
    payload = content if content is not None else (b"x" * (asset.file_size or 0))
    extension = asset.file_extension or "pdf"
    return MaterializedAsset(
        metadata=asset,
        content=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        mime_type="application/pdf" if extension == "pdf" else "image/jpeg",
        sanitized_filename=sanitize_asset_filename(
            asset.name,
            asset_id=asset.asset_id,
            extension=extension,
        ),
    )


class FakeStorage(StoragePort):
    def __init__(self) -> None:
        self.objects: dict[str, StorageObjectRecord] = {}
        self.uploads = 0
        self.adopts = 0

    def resolve(self, storage_key: str) -> StorageObjectRecord | None:
        return self.objects.get(storage_key)

    def upload(self, *, storage_key: str, materialized: MaterializedAsset) -> StorageObjectRecord:
        existing = self.objects.get(storage_key)
        if existing is not None:
            if existing.sha256 != materialized.sha256:
                raise MigrationAssetError("CONFLICT")
            self.adopts += 1
            return replace(existing, action="ADOPT_EXISTING_STORAGE_OBJECT")
        record = StorageObjectRecord(
            storage_key=storage_key,
            drive_file_id=f"drive-{len(self.objects)+1}",
            public_url=f"https://drive.example/file/{len(self.objects)+1}",
            sha256=materialized.sha256,
            size=len(materialized.content),
            mime_type=materialized.mime_type,
            original_filename=materialized.sanitized_filename,
            action="UPLOAD_REQUIRED",
        )
        self.objects[storage_key] = record
        self.uploads += 1
        return record


class FakeSunday:
    def __init__(self) -> None:
        self.attachments: dict[str, list[Attachment]] = {}
        self.created = 0

    def list_attachments(self, item_id: str) -> list[Attachment]:
        return list(self.attachments.get(item_id, []))

    def add_link_attachment(
        self,
        item_id: str,
        url: str,
        *,
        filename: str | None = None,
    ) -> Attachment:
        attachment = Attachment(id=str(self.created + 1), url=url, filename=filename)
        self.attachments.setdefault(item_id, []).append(attachment)
        self.created += 1
        return attachment


def test_single_pdf_attachment_manifest_and_accounting():
    asset = _asset(ASSET_A)
    digest = attachment_payload_digest(asset)
    assert digest == attachment_payload_digest(asset)
    assert digest != attachment_payload_digest(_asset(ASSET_A, name="other.pdf"))
    ops = (
        ManifestOperation(
            kind="ATTACHMENT",
            op_id=f"item:{ITEM}:asset:{ASSET_A}",
            monday_item_id=ITEM,
            payload_digest=digest,
        ),
    )
    accounting = summarize_manifest_accounting(ops)
    assert accounting.attachments == 1
    assert accounting.attachment_link_writes == 1
    assert accounting.storage_uploads == 1
    assert accounting.operation_total == 2


def test_two_pdf_multi_asset_manifest():
    assets = (_asset(ASSET_A), _asset(ASSET_B, name="other.pdf"))
    ops = tuple(
        sorted(
            [
                ManifestOperation(
                    kind="ATTACHMENT",
                    op_id=f"item:{ITEM}:asset:{asset.asset_id}",
                    monday_item_id=ITEM,
                    payload_digest=attachment_payload_digest(asset),
                )
                for asset in assets
            ],
            key=lambda row: row.op_id,
        ),
    )
    accounting = summarize_manifest_accounting(ops)
    assert accounting.attachments == 2
    assert accounting.storage_uploads == 2


def test_multi_asset_order_independent_manifest_hash():
    a1 = _asset(ASSET_A)
    a2 = _asset(ASSET_B, name="other.pdf")

    def manifest_for(assets):
        return tuple(
            sorted(
                [
                    ManifestOperation(
                        kind="ATTACHMENT",
                        op_id=f"item:{ITEM}:asset:{asset.asset_id}",
                        monday_item_id=ITEM,
                        payload_digest=attachment_payload_digest(asset),
                    )
                    for asset in assets
                ],
                key=lambda row: row.op_id,
            ),
        )

    first = manifest_for((a1, a2))
    second = manifest_for((a2, a1))
    assert operation_manifest_hash_v2(first) == operation_manifest_hash_v2(second)


def test_selected_source_changes_when_asset_added_or_removed():
    basis_one = assets_fingerprint_basis({ITEM: (_asset(ASSET_A),)}, item_ids=frozenset({ITEM}))
    basis_two = assets_fingerprint_basis(
        {ITEM: (_asset(ASSET_A), _asset(ASSET_B))},
        item_ids=frozenset({ITEM}),
    )
    assert basis_one != basis_two


def test_selected_source_changes_when_filename_or_size_changes():
    fp_base = assets_fingerprint_basis({ITEM: (_asset(ASSET_A),)}, item_ids=frozenset({ITEM}))
    fp_renamed = assets_fingerprint_basis(
        {ITEM: (_asset(ASSET_A, name="renamed.pdf"),)},
        item_ids=frozenset({ITEM}),
    )
    fp_resized = assets_fingerprint_basis(
        {ITEM: (_asset(ASSET_A, size=999),)},
        item_ids=frozenset({ITEM}),
    )
    assert fp_base != fp_renamed
    assert fp_base != fp_resized


def test_download_http_failure_aborts(monkeypatch):
    asset = _asset(ASSET_A)

    def boom(*_args, **_kwargs):
        raise MigrationAssetError("Download Monday asset 9001 HTTP 403.")

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_asset_download._resolve_download_target",
        lambda *_a, **_k: "https://example.test/file",
    )
    monkeypatch.setattr(
        "classificacao_procons.migration.monday_asset_download.urllib.request.urlopen",
        boom,
    )
    with pytest.raises(MigrationAssetError, match="403"):
        download_monday_asset("token", asset)


def test_download_partial_bytes_aborts(monkeypatch):
    asset = _asset(ASSET_A, size=200)

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def getcode(self):
            return 200

        def read(self):
            return b"x" * 50

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_asset_download._resolve_download_target",
        lambda *_a, **_k: "https://example.test/file",
    )
    monkeypatch.setattr(
        "classificacao_procons.migration.monday_asset_download.urllib.request.urlopen",
        lambda *_a, **_k: Resp(),
    )
    with pytest.raises(MigrationAssetError, match="parcial"):
        download_monday_asset("token", asset)


def test_hash_mismatch_aborts():
    asset = _asset(ASSET_A, size=10)
    materialized = _materialized(asset, b"0123456789")
    with pytest.raises(MigrationAssetError, match="Tamanho divergente"):
        materialized_matches_metadata(materialized, _asset(ASSET_A, size=11))


def test_storage_upload_then_adopt_on_rerun():
    asset = _asset(ASSET_A)
    materialized = _materialized(asset)
    storage = FakeStorage()
    key = build_storage_object_key(
        board_id=BOARD,
        item_id=ITEM,
        asset_id=ASSET_A,
        sanitized_filename=materialized.sanitized_filename,
    )
    first = storage.upload(storage_key=key, materialized=materialized)
    second = storage.upload(storage_key=first.storage_key, materialized=materialized)
    assert storage.uploads == 1
    assert storage.adopts == 1
    assert second.action == "ADOPT_EXISTING_STORAGE_OBJECT"


def test_storage_conflict_on_different_hash():
    asset = _asset(ASSET_A)
    storage = FakeStorage()
    key = build_storage_object_key(
        board_id=BOARD,
        item_id=ITEM,
        asset_id=ASSET_A,
        sanitized_filename="doc.pdf",
    )
    storage.upload(storage_key=key, materialized=_materialized(asset, b"one" * 20))
    with pytest.raises(MigrationAssetError, match="CONFLICT"):
        storage.upload(storage_key=key, materialized=_materialized(asset, b"two" * 20))


def test_sunday_attachment_idempotent_by_marker():
    asset = _asset(ASSET_A)
    storage_record = StorageObjectRecord(
        storage_key="k",
        drive_file_id="1",
        public_url="https://drive.example/1",
        sha256="abc",
        size=10,
        mime_type="application/pdf",
        original_filename="doc.pdf",
        action="UPLOAD_REQUIRED",
    )
    plan = plan_sunday_attachment(asset=asset, storage=storage_record)
    sunday = FakeSunday()
    first, created_first = ensure_sunday_link_attachment(sunday, sunday_item_id="999", plan=plan)
    second, created_second = ensure_sunday_link_attachment(sunday, sunday_item_id="999", plan=plan)
    assert created_first is True
    assert created_second is False
    assert first.id == second.id
    assert sunday.created == 1
    marker = asset_attachment_marker(board_id=BOARD, item_id=ITEM, asset_id=ASSET_A)
    assert marker in plan.attachment_filename


def test_end_to_end_mock_single_and_multi_asset_rerun_zero_writes():
    assets = (_asset(ASSET_A), _asset(ASSET_B, name="b.pdf"))
    storage = FakeStorage()
    sunday = FakeSunday()

    def downloader(_token, asset):
        return _materialized(asset)

    stats = BinaryAssetApplyStats()
    apply_item_assets(
        api_token="token",
        sunday_client=sunday,
        sunday_item_id="999",
        expected_assets=assets,
        storage=storage,
        stats=stats,
        downloader=downloader,
    )
    assert stats.asset_downloads == 2
    assert stats.storage_uploads == 2
    assert stats.attachment_link_writes == 2

    rerun_stats = BinaryAssetApplyStats()
    apply_item_assets(
        api_token="token",
        sunday_client=sunday,
        sunday_item_id="999",
        expected_assets=assets,
        storage=storage,
        stats=rerun_stats,
        downloader=downloader,
    )
    assert rerun_stats.storage_uploads == 0
    assert rerun_stats.storage_adopts == 2
    assert rerun_stats.attachment_link_writes == 0
    assert sunday.created == 2


def test_four_jpg_assets_each_get_attachment():
    assets = tuple(
        _asset(str(1000 + index), name=f"img{index}.jpg", size=50 + index, extension="jpg")
        for index in range(4)
    )
    storage = FakeStorage()
    sunday = FakeSunday()
    stats = BinaryAssetApplyStats()
    apply_item_assets(
        api_token="token",
        sunday_client=sunday,
        sunday_item_id="999",
        expected_assets=assets,
        storage=storage,
        stats=stats,
        downloader=lambda _t, asset: _materialized(asset, b"J" * (asset.file_size or 0)),
    )
    assert stats.attachment_link_writes == 4
    assert len(sunday.attachments["999"]) == 4


def test_unexpected_mime_fail_closed():
    with pytest.raises(MigrationAssetError, match="não suportado"):
        validate_asset_extension(_asset(ASSET_A, extension="exe"))


def test_classify_binary_ready_and_blocked():
    ready, reason = classify_binary_item_ready(
        disposition="CREATE",
        classification="WAVE_1_READY",
        blocked_reason=None,
        completeness_ok=True,
        asset_count=1,
    )
    assert ready is True
    assert reason == "BINARY_UPLOAD_REQUIRED"
    blocked, _ = classify_binary_item_ready(
        disposition="CREATE",
        classification="MANUAL",
        blocked_reason=None,
        completeness_ok=True,
        asset_count=1,
    )
    assert blocked is False


def test_migration_code_revision_changes_with_new_modules():
    revision = migration_code_revision()
    assert len(revision) == 24
    assert revision != OLD_CODE_REVISION


def test_reports_do_not_include_raw_urls_in_payload_digest():
    digest = attachment_payload_digest(_asset(ASSET_A))
    assert "http" not in digest
    assert "token" not in digest.lower()


def test_duplicate_sunday_attachment_marker_is_ambiguous():
    marker = asset_attachment_marker(board_id=BOARD, item_id=ITEM, asset_id=ASSET_A)
    attachments = [
        Attachment(id="1", filename=f"{marker} a.pdf"),
        Attachment(id="2", filename=f"{marker} b.pdf"),
    ]
    with pytest.raises(MigrationAssetError, match="AMBIGUOUS"):
        find_attachment_by_marker(attachments, marker)
