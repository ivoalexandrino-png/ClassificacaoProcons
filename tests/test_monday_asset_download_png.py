"""Testes de suporte PNG no pipeline binary Monday item.assets."""

from __future__ import annotations

import hashlib

import pytest

from classificacao_procons.migration.asset_attachment import asset_attachment_marker
from classificacao_procons.migration.asset_models import MigrationAssetError, MondayAssetMetadata
from classificacao_procons.migration.asset_preflight import approved_binary_asset_from_materialized
from classificacao_procons.migration.asset_storage import build_storage_object_key
from classificacao_procons.migration.monday_asset_download import (
    ALLOWED_ASSET_EXTENSIONS,
    DownloadTarget,
    download_monday_asset,
    guess_mime_type,
    sanitize_asset_filename,
    validate_asset_extension,
)

BOARD = "4944254220"
SUNDAY = "82"
ITEM = "6091959648"


def _asset(
    asset_id: str,
    *,
    name: str,
    size: int,
    extension: str,
) -> MondayAssetMetadata:
    return MondayAssetMetadata(
        board_id=BOARD,
        item_id=ITEM,
        asset_id=asset_id,
        name=name,
        file_size=size,
        file_extension=extension,
        created_at="2026-08-21T00:00:00Z",
    )


def _mock_download(monkeypatch, content: bytes) -> None:
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def getcode(self):
            return 200

        def read(self):
            return content

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_asset_download.resolve_download_target",
        lambda *_a, **_k: DownloadTarget(
            url="https://example.test/file",
            auth_mode="presigned",
        ),
    )
    monkeypatch.setattr(
        "classificacao_procons.migration.monday_asset_download.urllib.request.urlopen",
        lambda *_a, **_k: Resp(),
    )


def test_png_lowercase_extension_accepted():
    asset = _asset("1", name="screenshot.png", size=8, extension="png")
    validate_asset_extension(asset)


def test_png_uppercase_extension_accepted():
    asset = _asset("2", name="screenshot.PNG", size=8, extension="PNG")
    validate_asset_extension(asset)


def test_png_bytes_preserved_on_download(monkeypatch):
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    asset = _asset("3", name="capture.png", size=len(content), extension="png")
    _mock_download(monkeypatch, content)
    materialized = download_monday_asset("token", asset)
    assert materialized.content == content


def test_png_size_matches_metadata(monkeypatch):
    content = b"\x89PNG\r\n\x1a\n" + b"\x01" * 12
    asset = _asset("4", name="size.png", size=len(content), extension="png")
    _mock_download(monkeypatch, content)
    materialized = download_monday_asset("token", asset)
    assert len(materialized.content) == asset.file_size


def test_png_sha256_matches_content(monkeypatch):
    content = b"\x89PNG\r\n\x1a\n" + b"\x02" * 16
    asset = _asset("5", name="hash.png", size=len(content), extension="png")
    _mock_download(monkeypatch, content)
    materialized = download_monday_asset("token", asset)
    assert materialized.sha256 == hashlib.sha256(content).hexdigest()


def test_unsupported_extension_still_blocked():
    asset = _asset("6", name="virus.exe", size=4, extension="exe")
    with pytest.raises(MigrationAssetError, match="não suportado"):
        validate_asset_extension(asset)


@pytest.mark.parametrize("extension", ["pdf", "jpg", "jpeg"])
def test_existing_extensions_regression(extension: str):
    asset = _asset("7", name=f"file.{extension}", size=4, extension=extension)
    validate_asset_extension(asset)


def test_png_mime_type_supported():
    assert guess_mime_type("capture.png", "png") == "image/png"
    assert guess_mime_type("capture.PNG", "PNG") == "image/png"


def test_png_storage_identity_unchanged(monkeypatch):
    content = b"\x89PNG\r\n\x1a\n" + b"\x03" * 10
    asset = _asset("8", name="identity.png", size=len(content), extension="png")
    _mock_download(monkeypatch, content)
    materialized = download_monday_asset("token", asset)
    approved = approved_binary_asset_from_materialized(
        materialized=materialized,
        sunday_board_id=SUNDAY,
    )
    expected_key = build_storage_object_key(
        board_id=BOARD,
        item_id=ITEM,
        asset_id=asset.asset_id,
        sanitized_filename=sanitize_asset_filename(
            asset.name,
            asset_id=asset.asset_id,
            extension=asset.file_extension,
        ),
    )
    assert approved.storage_object_key == expected_key
    marker = asset_attachment_marker(
        board_id=BOARD,
        item_id=ITEM,
        asset_id=asset.asset_id,
    )
    assert marker == f"[monday-asset:{BOARD}:{ITEM}:{asset.asset_id}]"


def test_same_sha_distinct_asset_id_keeps_distinct_identities(monkeypatch):
    content = b"\x89PNG\r\n\x1a\n" + b"\x04" * 20
    asset_a = _asset("100", name="a.png", size=len(content), extension="png")
    asset_b = _asset("200", name="b.png", size=len(content), extension="png")
    _mock_download(monkeypatch, content)
    mat_a = download_monday_asset("token", asset_a)
    mat_b = download_monday_asset("token", asset_b)
    assert mat_a.sha256 == mat_b.sha256
    approved_a = approved_binary_asset_from_materialized(
        materialized=mat_a,
        sunday_board_id=SUNDAY,
    )
    approved_b = approved_binary_asset_from_materialized(
        materialized=mat_b,
        sunday_board_id=SUNDAY,
    )
    assert approved_a.storage_object_key != approved_b.storage_object_key
    assert approved_a.asset_id != approved_b.asset_id


def test_allowed_extensions_include_png():
    assert "png" in ALLOWED_ASSET_EXTENSIONS
