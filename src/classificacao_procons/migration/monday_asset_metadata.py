"""Leitura de metadata Monday item.assets (PLAN — sem download)."""

from __future__ import annotations

from classificacao_procons.migration.asset_models import MigrationAssetError, MondayAssetMetadata
from classificacao_procons.migration.monday_inventory import _graphql_request

_ASSET_METADATA_QUERY = """
query ($ids: [ID!]!) {
  items(ids: $ids) {
    id
    assets {
      id
      name
      file_size
      file_extension
      created_at
    }
  }
}
"""


def parse_asset_row(*, board_id: str, item_id: str, row: dict) -> MondayAssetMetadata:
    asset_id = str(row.get("id") or "").strip()
    if not asset_id:
        raise MigrationAssetError("Asset Monday sem id.")
    name = str(row.get("name") or "").strip() or f"asset-{asset_id}"
    size_raw = row.get("file_size")
    file_size = int(size_raw) if size_raw is not None else None
    extension = str(row.get("file_extension") or "").strip() or None
    created_at = str(row.get("created_at") or "").strip() or None
    return MondayAssetMetadata(
        board_id=board_id,
        item_id=item_id,
        asset_id=asset_id,
        name=name,
        file_size=file_size,
        file_extension=extension,
        created_at=created_at,
    )


def fetch_item_assets_metadata(
    api_token: str,
    *,
    board_id: str,
    item_ids: set[str] | frozenset[str],
    batch_size: int = 25,
) -> dict[str, tuple[MondayAssetMetadata, ...]]:
    """Retorna assets por item, ordenados por asset_id (determinístico)."""
    if not item_ids:
        return {}
    result: dict[str, tuple[MondayAssetMetadata, ...]] = {}
    ordered = sorted(item_ids)
    for offset in range(0, len(ordered), batch_size):
        batch = ordered[offset : offset + batch_size]
        rows = _graphql_request(
            api_token=api_token,
            query=_ASSET_METADATA_QUERY,
            variables={"ids": batch},
        ).get("items") or []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            item_id = str(row.get("id") or "").strip()
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            assets = [
                parse_asset_row(board_id=board_id, item_id=item_id, row=asset)
                for asset in row.get("assets") or []
                if isinstance(asset, dict)
            ]
            assets.sort(key=lambda asset: asset.asset_id)
            result[item_id] = tuple(assets)
    missing = set(item_ids) - set(result)
    if missing:
        raise MigrationAssetError(
            f"Metadata assets ausente para itens: {', '.join(sorted(missing))}.",
        )
    return result


def assets_fingerprint_basis(
    assets_by_item: dict[str, tuple[MondayAssetMetadata, ...]],
    *,
    item_ids: frozenset[str],
) -> tuple[tuple[object, ...], ...]:
    basis: list[tuple[object, ...]] = []
    for item_id in sorted(item_ids):
        assets = assets_by_item.get(item_id, ())
        basis.append(
            (
                item_id,
                tuple(asset.fingerprint_tuple for asset in assets),
            ),
        )
    return tuple(basis)
