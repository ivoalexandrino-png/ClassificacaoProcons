"""Consulta de casos no Monday.com para elaboração de resposta."""

from __future__ import annotations

from classificacao_procons.models import MondayCaseReady
from classificacao_procons.monday.client import (
    DEFAULT_BOARD_NAME,
    _graphql_request,
    _normalize_name,
    get_api_token_from_env,
    load_board_metadata,
)
from classificacao_procons.monday.mapping import (
    FIELD_DOCS_SAC,
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
    }

    for column_value in item.get("column_values", []):
        field = column_lookup.get(column_value.get("id", ""), "")
        if not field:
            continue
        if field == FIELD_DOCS_SAC:
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
        status=status,
    )


def list_cases_ready_for_elaboration(
    *,
    api_token: str | None = None,
    board_name: str = DEFAULT_BOARD_NAME,
    limit: int = 50,
) -> list[MondayCaseReady]:
    """Lista casos com Docs SAC preenchido e ainda sem status final."""
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
        query ($boardId: [ID!], $limit: Int!) {
          boards(ids: $boardId) {
            groups {
              id
              title
              items_page(limit: $limit) {
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
        variables={"boardId": context.board_id, "limit": limit},
    )

    boards = data.get("boards", [])
    if not boards:
        return []

    column_lookup = _build_column_lookup(context.columns)
    cases: list[MondayCaseReady] = []

    for group in boards[0].get("groups", []):
        for item in group.get("items_page", {}).get("items", []):
            case = _extract_case_from_item(item, column_lookup=column_lookup)
            if case is not None:
                cases.append(case)

    return cases
