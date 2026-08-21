"""Download autenticado de Monday item.assets (APPLY only)."""

from __future__ import annotations

import hashlib
import mimetypes
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Literal

from classificacao_procons.migration.asset_models import (
    MaterializedAsset,
    MigrationAssetError,
    MondayAssetMetadata,
)
from classificacao_procons.migration.monday_inventory import _graphql_request

_ASSET_URL_QUERY = """
query ($ids: [ID!]!) {
  assets(ids: $ids) {
    id
    url
    public_url
  }
}
"""

MONDAY_FILES_API = "https://api.monday.com/v2/files"

ALLOWED_ASSET_EXTENSIONS = frozenset({"pdf", "jpg", "jpeg", "png"})

DownloadAuthMode = Literal["monday_auth", "presigned"]


@dataclass(frozen=True)
class DownloadTarget:
    url: str
    auth_mode: DownloadAuthMode


def validate_asset_extension(asset: MondayAssetMetadata) -> None:
    extension = (asset.file_extension or "").lower().lstrip(".")
    if extension and extension not in ALLOWED_ASSET_EXTENSIONS:
        raise MigrationAssetError(
            f"Tipo de asset não suportado: {extension or 'desconhecido'}.",
        )


def sanitize_asset_filename(name: str, *, asset_id: str, extension: str | None) -> str:
    cleaned = " ".join(name.split()).strip()
    cleaned = re.sub(r'[\\/:*?"<>|]', "-", cleaned)
    if not cleaned:
        cleaned = f"monday-asset-{asset_id}"
    if extension and not cleaned.lower().endswith(f".{extension.lower().lstrip('.')}"):
        cleaned = f"{cleaned}.{extension.lstrip('.')}"
    return cleaned[:200]


def guess_mime_type(filename: str, extension: str | None) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    if guessed:
        return guessed
    if extension:
        ext_guess, _ = mimetypes.guess_type(f"file.{extension.lstrip('.')}")
        if ext_guess:
            return ext_guess
    return "application/octet-stream"


def classify_download_auth_mode(url: str) -> DownloadAuthMode:
    """Presigned/S3 não aceitam Authorization Monday; endpoints Monday exigem."""
    lowered = url.lower()
    if lowered.startswith(MONDAY_FILES_API.lower()):
        return "monday_auth"
    if "files-monday-com.s3" in lowered:
        return "presigned"
    if ".s3." in lowered and "amazonaws.com" in lowered:
        return "presigned"
    if "monday.com" in lowered:
        return "monday_auth"
    return "presigned"


def build_download_request(target: DownloadTarget, api_token: str) -> urllib.request.Request:
    headers = {"User-Agent": "ClassificacaoProcons/1.0"}
    if target.auth_mode == "monday_auth":
        headers["Authorization"] = api_token
    return urllib.request.Request(target.url, headers=headers)


def resolve_download_target(api_token: str, asset: MondayAssetMetadata) -> DownloadTarget:
    rows = _graphql_request(
        api_token=api_token,
        query=_ASSET_URL_QUERY,
        variables={"ids": [asset.asset_id]},
    ).get("assets") or []
    if not rows:
        raise MigrationAssetError(f"Asset Monday {asset.asset_id} não encontrado para download.")
    row = rows[0]
    public_url = str(row.get("public_url") or "").strip()
    monday_url = str(row.get("url") or "").strip()
    if public_url.startswith(("http://", "https://")):
        return DownloadTarget(url=public_url, auth_mode=classify_download_auth_mode(public_url))
    if monday_url.startswith(("http://", "https://")):
        return DownloadTarget(url=monday_url, auth_mode=classify_download_auth_mode(monday_url))
    return DownloadTarget(
        url=f"{MONDAY_FILES_API}/{asset.asset_id}",
        auth_mode="monday_auth",
    )


def download_monday_asset(
    api_token: str,
    asset: MondayAssetMetadata,
    *,
    http_opener=None,
) -> MaterializedAsset:
    """Baixa bytes via autenticação Monday; valida tamanho quando conhecido."""
    target = resolve_download_target(api_token, asset)
    request = build_download_request(target, api_token)
    opener = http_opener or urllib.request.urlopen
    try:
        with opener(request, timeout=120) as response:
            status = getattr(response, "status", None) or response.getcode()
            if status and int(status) >= 400:
                raise MigrationAssetError(
                    f"Download Monday asset {asset.asset_id} HTTP {status}.",
                )
            content = response.read()
    except urllib.error.HTTPError as exc:
        raise MigrationAssetError(
            f"Download Monday asset {asset.asset_id} HTTP {exc.code}.",
        ) from exc
    except urllib.error.URLError as exc:
        raise MigrationAssetError(
            f"Download Monday asset {asset.asset_id} falhou: {exc.reason}.",
        ) from exc

    if asset.file_size is not None and len(content) != asset.file_size:
        raise MigrationAssetError(
            f"Tamanho divergente asset {asset.asset_id}: "
            f"{len(content)} != {asset.file_size}.",
        )

    sanitized = sanitize_asset_filename(
        asset.name,
        asset_id=asset.asset_id,
        extension=asset.file_extension,
    )
    sha256 = hashlib.sha256(content).hexdigest()
    mime = guess_mime_type(sanitized, asset.file_extension)
    return MaterializedAsset(
        metadata=asset,
        content=content,
        sha256=sha256,
        mime_type=mime,
        sanitized_filename=sanitized,
    )


def materialized_matches_metadata(
    materialized: MaterializedAsset,
    expected: MondayAssetMetadata,
) -> None:
    if materialized.metadata.asset_id != expected.asset_id:
        raise MigrationAssetError("Asset_id divergente após materialização.")
    if expected.file_size is not None and len(materialized.content) != expected.file_size:
        raise MigrationAssetError(
            f"Tamanho divergente asset {expected.asset_id}: "
            f"{len(materialized.content)} != {expected.file_size}.",
        )
