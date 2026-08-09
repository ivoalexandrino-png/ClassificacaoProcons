"""Leitura do quadro KPI - Processos Consumidores no Monday."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from classificacao_procons.juridico.casos import (
    DEFAULT_KPI_BOARD_NAME,
    ENV_KPI_BOARD_ID,
    _board_columns_with_settings,
    _board_id_from_env_or_name,
    _find_cnj_column,
)
from classificacao_procons.juridico.cnj import extract_process_number
from classificacao_procons.juridico.monday import _normalize_title
from classificacao_procons.monday.client import (
    MondayClientError,
    _build_item_url,
    _graphql_request,
    get_api_token_from_env,
)

_CNJ_DIGITS = re.compile(r"\d{20}")


@dataclass(frozen=True)
class KpiProcessRow:
    process_number: str
    item_id: str
    item_name: str
    item_url: str | None
    condemnation_brl: Decimal | None
    paid_brl: Decimal | None
    result_label: str | None


def _parse_money(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    cleaned = cleaned.replace("R$", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _column_text_by_title(columns: list[dict], item: dict, *title_parts: str) -> str | None:
    targets = {_normalize_title(part) for part in title_parts}
    column_by_id = {str(column["id"]): column for column in columns}
    for column_value in item.get("column_values", []):
        column_id = str(column_value.get("id", ""))
        column = column_by_id.get(column_id)
        if column is None:
            continue
        title = _normalize_title(str(column.get("title", "")))
        if any(part in title for part in targets):
            text = (column_value.get("text") or "").strip()
            if text:
                return text
    return None


def _extract_process_from_item(
    *,
    item: dict,
    cnj_column_id: str | None,
) -> str | None:
    if cnj_column_id:
        for column_value in item.get("column_values", []):
            if str(column_value.get("id")) != cnj_column_id:
                continue
            text = (column_value.get("text") or "").strip()
            if text:
                found = extract_process_number(text)
                if found:
                    return found
    combined = f"{item.get('name', '')}"
    for column_value in item.get("column_values", []):
        combined += f" {column_value.get('text') or ''}"
    found = extract_process_number(combined)
    if found:
        return found
    digits = "".join(char for char in combined if char.isdigit())
    match = _CNJ_DIGITS.search(digits)
    if match:
        formatted = extract_process_number(match.group(0))
        return formatted
    return None


def _fetch_kpi_board_id(api_token: str) -> str | None:
    return _board_id_from_env_or_name(
        api_token=api_token,
        env_name=ENV_KPI_BOARD_ID,
        board_name=DEFAULT_KPI_BOARD_NAME,
    )


def load_kpi_process_rows(*, api_token: str | None = None) -> list[KpiProcessRow]:
    token = api_token or get_api_token_from_env()
    if not token:
        return []

    board_id = _fetch_kpi_board_id(token)
    if not board_id:
        return []

    board = _board_columns_with_settings(token, board_id)
    columns = board.get("columns", [])
    cnj_column = _find_cnj_column(columns)
    cnj_column_id = str(cnj_column["id"]) if cnj_column else None

    rows: list[KpiProcessRow] = []
    cursor: str | None = None
    account_slug: str | None = None

    while True:
        try:
            data = _graphql_request(
                api_token=token,
                query="""
                query ($boardId: ID!, $limit: Int!, $cursor: String) {
                  boards(ids: [$boardId]) {
                    id
                    items_page(limit: $limit, cursor: $cursor) {
                      cursor
                      items {
                        id
                        name
                        column_values { id text value }
                      }
                    }
                  }
                }
                """,
                variables={"boardId": board_id, "limit": 100, "cursor": cursor},
            )
        except MondayClientError:
            break

        boards = data.get("boards", [])
        if not boards:
            break
        page = boards[0].get("items_page", {})
        for item in page.get("items", []):
            process_number = _extract_process_from_item(item=item, cnj_column_id=cnj_column_id)
            if not process_number:
                continue
            condemnation_text = _column_text_by_title(
                columns,
                item,
                "condenacao",
                "condenação",
                "valor condenacao",
                "valor da condenacao",
            )
            paid_text = _column_text_by_title(
                columns,
                item,
                "pago",
                "valor pago",
                "pagamento",
            )
            result_label = _column_text_by_title(columns, item, "resultado", "decisao", "decisão")
            item_id = str(item["id"])
            rows.append(
                KpiProcessRow(
                    process_number=process_number,
                    item_id=item_id,
                    item_name=str(item.get("name", "")),
                    item_url=_build_item_url(
                        board_id=board_id,
                        item_id=item_id,
                        account_slug=account_slug,
                    ),
                    condemnation_brl=_parse_money(condemnation_text),
                    paid_brl=_parse_money(paid_text),
                    result_label=result_label,
                ),
            )

        cursor = page.get("cursor")
        if not cursor:
            break

    return rows


def index_kpi_by_process(rows: list[KpiProcessRow]) -> dict[str, KpiProcessRow]:
    indexed: dict[str, KpiProcessRow] = {}
    for row in rows:
        indexed[row.process_number] = row
    return indexed


def index_kpi_by_consumer_name(rows: list[KpiProcessRow]) -> dict[str, KpiProcessRow]:
    indexed: dict[str, KpiProcessRow] = {}
    for row in rows:
        key = _normalize_title(row.item_name)
        if key:
            indexed[key] = row
    return indexed
