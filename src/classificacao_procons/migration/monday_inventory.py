"""Inventário read-only dos boards do Monday para a Fase 2.

Usa a API GraphQL do Monday exclusivamente em leitura e produz digests
SANITIZADOS (`MondayItemDigest`): nenhum nome de item, texto, CPF/CNPJ ou conteúdo
de update é retido — apenas ids, grupo, datas, labels de status (schema), ids de
pessoas, contagens de arquivos/subitens e alvos de conexão.
"""

from __future__ import annotations

import json

from classificacao_procons.migration.models import (
    MondayBoardInventory,
    MondayColumnInfo,
    MondayItemDigest,
)
from classificacao_procons.monday.client import _graphql_request

ITEMS_PAGE_SIZE = 250
UPDATES_PAGE_SIZE = 100
UPDATES_MAX_PAGES = 30

_BOARD_META_QUERY = """
query ($ids: [ID!]) {
  boards(ids: $ids) {
    id
    name
    groups { id title }
    columns { id title type settings_str }
  }
}
"""

_ITEMS_PAGE_QUERY = """
query ($ids: [ID!], $cursor: String, $limit: Int!) {
  boards(ids: $ids) {
    items_page(limit: $limit, cursor: $cursor) {
      cursor
      items {
        id
        created_at
        updated_at
        group { id }
        parent_item { id }
        subitems { id }
        assets { id file_size }
        updates(limit: 1) { id }
        column_values {
          id
          type
          text
          value
          ... on BoardRelationValue { linked_item_ids }
        }
      }
    }
  }
}
"""

_BOARD_UPDATES_QUERY = """
query ($ids: [ID!], $limit: Int!, $page: Int!) {
  boards(ids: $ids) {
    updates(limit: $limit, page: $page) { id }
  }
}
"""


def _parse_settings(settings_str: object) -> dict:
    if not settings_str:
        return {}
    try:
        parsed = json.loads(str(settings_str))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _relation_targets(value_json: object) -> tuple[str, ...]:
    """Extrai linkedPulseIds do value JSON (fallback; o caminho principal é o
    campo tipado `linked_item_ids` — o `value` genérico volta vazio para
    board_relation na API 2024-10, confirmado no inventário real)."""
    if not value_json:
        return ()
    try:
        payload = json.loads(str(value_json))
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, dict):
        return ()
    linked = payload.get("linkedPulseIds")
    if not isinstance(linked, list):
        return ()
    targets = []
    for entry in linked:
        if isinstance(entry, dict) and entry.get("linkedPulseId") is not None:
            targets.append(str(entry["linkedPulseId"]))
    return tuple(targets)


def _people_ids(value_json: object) -> tuple[str, ...]:
    if not value_json:
        return ()
    try:
        payload = json.loads(str(value_json))
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, dict):
        return ()
    persons = payload.get("personsAndTeams")
    if not isinstance(persons, list):
        return ()
    return tuple(
        str(person["id"])
        for person in persons
        if isinstance(person, dict) and person.get("kind") == "person" and person.get("id")
    )


def _digest_item(item: dict, columns_by_id: dict[str, MondayColumnInfo]) -> MondayItemDigest:
    status_labels: dict[str, str] = {}
    people: list[str] = []
    relations: dict[str, tuple[str, ...]] = {}
    for value in item.get("column_values", []):
        column_id = str(value.get("id", ""))
        column = columns_by_id.get(column_id)
        if column is None:
            continue
        if column.type == "status":
            label = (value.get("text") or "").strip()
            if label:
                status_labels[column_id] = label
        elif column.type == "people":
            people.extend(_people_ids(value.get("value")))
        elif column.type == "board_relation":
            linked = value.get("linked_item_ids")
            targets = (
                tuple(str(target) for target in linked)
                if isinstance(linked, list) and linked
                else _relation_targets(value.get("value"))
            )
            if targets:
                relations[column_id] = targets
    assets = [asset for asset in item.get("assets") or [] if isinstance(asset, dict)]
    return MondayItemDigest(
        item_id=str(item["id"]),
        group_id=(item.get("group") or {}).get("id"),
        created_at=item.get("created_at"),
        updated_at=item.get("updated_at"),
        status_labels=status_labels,
        people_ids=tuple(dict.fromkeys(people)),
        file_count=len(assets),
        file_bytes=sum(int(asset.get("file_size") or 0) for asset in assets),
        has_updates=bool(item.get("updates")),
        subitem_count=len(item.get("subitems") or []),
        relation_targets=relations,
    )


def fetch_board_inventory(
    api_token: str,
    board_id: str,
    *,
    include_updates_count: bool = True,
) -> MondayBoardInventory:
    """Busca schema + digests sanitizados de todos os itens do board (read-only)."""
    meta = _graphql_request(
        api_token=api_token, query=_BOARD_META_QUERY, variables={"ids": [board_id]},
    )["boards"][0]
    columns = tuple(
        MondayColumnInfo(
            id=str(column["id"]),
            title=str(column.get("title", "")),
            type=str(column.get("type", "")),
            settings=_parse_settings(column.get("settings_str")),
        )
        for column in meta.get("columns", [])
    )
    columns_by_id = {column.id: column for column in columns}
    groups = {
        str(group["id"]): str(group.get("title", "")) for group in meta.get("groups", [])
    }

    items: list[MondayItemDigest] = []
    cursor: str | None = None
    while True:
        page = _graphql_request(
            api_token=api_token,
            query=_ITEMS_PAGE_QUERY,
            variables={"ids": [board_id], "cursor": cursor, "limit": ITEMS_PAGE_SIZE},
        )["boards"][0]["items_page"]
        for item in page.get("items", []):
            items.append(_digest_item(item, columns_by_id))
        cursor = page.get("cursor")
        if not cursor:
            break

    updates_count = 0
    updates_lower_bound = False
    if include_updates_count:
        for page_number in range(1, UPDATES_MAX_PAGES + 1):
            updates = _graphql_request(
                api_token=api_token,
                query=_BOARD_UPDATES_QUERY,
                variables={"ids": [board_id], "limit": UPDATES_PAGE_SIZE, "page": page_number},
            )["boards"][0].get("updates", [])
            updates_count += len(updates)
            if len(updates) < UPDATES_PAGE_SIZE:
                break
        else:
            updates_lower_bound = True

    return MondayBoardInventory(
        board_id=str(meta["id"]),
        name=str(meta.get("name", "")),
        groups=groups,
        columns=columns,
        items=tuple(items),
        updates_count_capped=updates_count,
        updates_count_is_lower_bound=updates_lower_bound,
    )


def inventory_to_payload(inventory: MondayBoardInventory) -> dict:
    """Serializa o inventário sanitizado para JSON (snapshot versionável)."""
    return {
        "board_id": inventory.board_id,
        "name": inventory.name,
        "groups": inventory.groups,
        "columns": [
            {
                "id": column.id,
                "title": column.title,
                "type": column.type,
                "settings": column.settings,
            }
            for column in inventory.columns
        ],
        "items": [
            {
                "item_id": item.item_id,
                "group_id": item.group_id,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "status_labels": item.status_labels,
                "people_ids": list(item.people_ids),
                "file_count": item.file_count,
                "file_bytes": item.file_bytes,
                "has_updates": item.has_updates,
                "subitem_count": item.subitem_count,
                "relation_targets": {
                    key: list(value) for key, value in item.relation_targets.items()
                },
            }
            for item in inventory.items
        ],
        "updates_count_capped": inventory.updates_count_capped,
        "updates_count_is_lower_bound": inventory.updates_count_is_lower_bound,
    }


def inventory_from_payload(payload: dict) -> MondayBoardInventory:
    columns = tuple(
        MondayColumnInfo(
            id=str(column["id"]),
            title=str(column.get("title", "")),
            type=str(column.get("type", "")),
            settings=column.get("settings") or {},
        )
        for column in payload.get("columns", [])
    )
    items = tuple(
        MondayItemDigest(
            item_id=str(item["item_id"]),
            group_id=item.get("group_id"),
            created_at=item.get("created_at"),
            updated_at=item.get("updated_at"),
            status_labels=item.get("status_labels") or {},
            people_ids=tuple(item.get("people_ids") or ()),
            file_count=int(item.get("file_count") or 0),
            file_bytes=int(item.get("file_bytes") or 0),
            has_updates=bool(item.get("has_updates")),
            subitem_count=int(item.get("subitem_count") or 0),
            relation_targets={
                key: tuple(value)
                for key, value in (item.get("relation_targets") or {}).items()
            },
        )
        for item in payload.get("items", [])
    )
    return MondayBoardInventory(
        board_id=str(payload["board_id"]),
        name=str(payload.get("name", "")),
        groups=payload.get("groups") or {},
        columns=columns,
        items=items,
        updates_count_capped=int(payload.get("updates_count_capped") or 0),
        updates_count_is_lower_bound=bool(payload.get("updates_count_is_lower_bound")),
    )
