"""Consulta de casos no Monday.com para elaboração de resposta."""

from __future__ import annotations

from classificacao_procons.models import MondayCaseReady
from classificacao_procons.monday.client import (
    DEFAULT_BOARD_NAME,
    DEFAULT_GROUP_NAME,
    _graphql_request,
    _normalize_name,
    get_api_token_from_env,
    load_board_metadata,
)
from classificacao_procons.monday.mapping import (
    FIELD_DOCS_SAC,
    FIELD_PDF_URL,
    FIELD_PROTOCOL,
    FIELD_STATUS,
    MondayColumn,
    parse_link_column_value,
    parse_status_text,
    resolve_field_for_column,
)

CLOSED_STATUS_KEYWORDS = ("respondido", "baixado")


def _build_column_lookup(columns: list[MondayColumn]) -> dict[str, str]:
    return {column.id: resolve_field_for_column(column.title) or "" for column in columns}


def _extract_case_from_item(
    item: dict,
    *,
    column_lookup: dict[str, str],
) -> MondayCaseReady | None:
    values: dict[str, str | None] = {
        FIELD_DOCS_SAC: None,
        FIELD_PROTOCOL: None,
        FIELD_STATUS: None,
        FIELD_PDF_URL: None,
    }

    for column_value in item.get("column_values", []):
        field = column_lookup.get(column_value.get("id", ""), "")
        if not field:
            continue
        if field in {FIELD_DOCS_SAC, FIELD_PDF_URL}:
            link = parse_link_column_value(column_value.get("value"))
            values[field] = link or column_value.get("text")
        elif field == FIELD_STATUS:
            values[field] = parse_status_text(column_value.get("text"))
        else:
            values[field] = (column_value.get("text") or "").strip() or None

    docs_sac_url = values.get(FIELD_DOCS_SAC)
    if not docs_sac_url:
        return None

    status = values.get(FIELD_STATUS)
    if status and any(keyword in _normalize_name(status) for keyword in CLOSED_STATUS_KEYWORDS):
        return None

    return MondayCaseReady(
        item_id=str(item["id"]),
        item_name=str(item.get("name", "")).strip(),
        docs_sac_url=docs_sac_url,
        protocol_number=values.get(FIELD_PROTOCOL),
        complaint_pdf_url=values.get(FIELD_PDF_URL),
        status=status,
    )


def _filter_pending_groups(groups: list[dict], group_name: str) -> list[dict]:
    target = _normalize_name(group_name)
    return [
        group
        for group in groups
        if _normalize_name(str(group.get("title", ""))) == target
    ]


def list_cases_ready_for_elaboration(
    *,
    api_token: str | None = None,
    board_name: str = DEFAULT_BOARD_NAME,
    group_name: str = DEFAULT_GROUP_NAME,
    limit: int = 50,
    page_size: int = 100,
    max_items_scanned: int = 100,
) -> list[MondayCaseReady]:
    """Lista casos com Docs SAC no grupo Pendentes de Resposta."""
    token = api_token or get_api_token_from_env()
    if not token:
        return []

    context = load_board_metadata(
        api_token=token,
        board_name=board_name,
    )

    data = _graphql_request(
        api_token=token,
        query="""
        query ($boardId: [ID!]) {
          boards(ids: $boardId) {
            groups {
              id
              title
            }
          }
        }
        """,
        variables={"boardId": context.board_id},
    )

    boards = data.get("boards", [])
    if not boards:
        return []

    column_lookup = _build_column_lookup(context.columns)
    cases: list[MondayCaseReady] = []
    items_scanned = 0

    pending_groups = _filter_pending_groups(boards[0].get("groups", []), group_name)
    if not pending_groups:
        return []

    for group in pending_groups:
        cursor: str | None = None
        while items_scanned < max_items_scanned and len(cases) < limit:
            page_limit = min(page_size, max_items_scanned - items_scanned)
            page_data = _graphql_request(
                api_token=token,
                query="""
                query ($boardId: ID!, $groupId: String!, $limit: Int!, $cursor: String) {
                  boards(ids: [$boardId]) {
                    groups(ids: [$groupId]) {
                      items_page(limit: $limit, cursor: $cursor) {
                        cursor
                        items {
                          id
                          name
                          column_values {
                            id
                            text
                            value
                          }
                        }
                      }
                    }
                  }
                }
                """,
                variables={
                    "boardId": context.board_id,
                    "groupId": group["id"],
                    "limit": page_limit,
                    "cursor": cursor,
                },
            )

            group_pages = page_data.get("boards", [{}])[0].get("groups", [])
            if not group_pages:
                break

            page = group_pages[0].get("items_page", {})
            items = page.get("items", [])
            if not items:
                break

            for item in items:
                items_scanned += 1
                case = _extract_case_from_item(item, column_lookup=column_lookup)
                if case is not None:
                    cases.append(case)
                    if len(cases) >= limit:
                        return cases

            cursor = page.get("cursor")
            if not cursor:
                break

    return cases


def fetch_case_by_item_id(
    *,
    api_token: str | None = None,
    item_id: str,
    board_name: str = DEFAULT_BOARD_NAME,
) -> MondayCaseReady | None:
    """Busca um caso específico no Monday pelo ID do item."""
    token = api_token or get_api_token_from_env()
    if not token:
        return None

    context = load_board_metadata(
        api_token=token,
        board_name=board_name,
    )
    data = _graphql_request(
        api_token=token,
        query="""
        query ($itemIds: [ID!]) {
          items(ids: $itemIds) {
            id
            name
            column_values {
              id
              text
              value
            }
          }
        }
        """,
        variables={"itemIds": item_id},
    )

    items = data.get("items", [])
    if not items:
        return None

    column_lookup = _build_column_lookup(context.columns)
    return _extract_case_from_item(items[0], column_lookup=column_lookup)
