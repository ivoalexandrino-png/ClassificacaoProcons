"""Download autenticado de Monday item.assets (APPLY only)."""

from __future__ import annotations

import hashlib
import mimetypes
import re
import urllib.error
import urllib.request

from classificacao_procons.migration.asset_models import (
    MaterializedAsset,
    MigrationAssetError,
    MondayAssetMetadata,
)
from classificacao_procons.migration.monday_inventory import _graphql_request

_ASSET_URL_QUERY = """
query ($ids: [ID!]!) {
  items(ids: $ids) {
    id
    assets {
      id
      url
      public_url
    }
  }
}
"""

MONDAY_FILES_API = "https://api.monday.com/v2/files"


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


def _resolve_download_target(
    api_token: str,
    asset: MondayAssetMetadata,
) -> str:
    rows = _graphql_request(
        api_token=api_token,
        query=_ASSET_URL_QUERY,
        variables={"ids": [asset.item_id]},
    ).get("items") or []
    if not rows:
        raise MigrationAssetError(f"Item Monday {asset.item_id} não encontrado para download.")
    item_row = rows[0]
    for row in item_row.get("assets") or []:
        if str(row.get("id")) == asset.asset_id:
            url = str(row.get("public_url") or row.get("url") or "").strip()
            if url.startswith("http://") or url.startswith("https://"):
                return url
            break
    return f"{MONDAY_FILES_API}/{asset.asset_id}"


def download_monday_asset(
    api_token: str,
    asset: MondayAssetMetadata,
    *,
    http_opener=None,
) -> MaterializedAsset:
    """Baixa bytes via autenticação Monday; valida tamanho quando conhecido."""
    target = _resolve_download_target(api_token, asset)
    request = urllib.request.Request(
        target,
        headers={"Authorization": api_token, "User-Agent": "ClassificacaoProcons/1.0"},
    )
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

    if asset.file_size is not None and len(content) < asset.file_size:
        raise MigrationAssetError(
            f"Download parcial asset {asset.asset_id}: "
            f"{len(content)} < {asset.file_size} bytes esperados.",
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
