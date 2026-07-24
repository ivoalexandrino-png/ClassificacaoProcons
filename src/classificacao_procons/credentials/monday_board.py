"""Leitura do board Acessos (credenciais) no Monday.com."""

from __future__ import annotations

import os
from dataclasses import dataclass

from classificacao_procons.credentials.mapping import (
    DEFAULT_CREDENTIALS_GROUP_NAME,
    default_portal_url,
    elemento_matches_source,
    normalize_label,
    resolve_field_for_column,
)
from classificacao_procons.credentials.models import PortalCredentials
from classificacao_procons.monday.client import MondayClientError, _graphql_request
from classificacao_procons.monday.mapping import MondayColumn, parse_link_column_value

ENV_CREDENTIALS_BOARD_ID = "MONDAY_CREDENTIALS_BOARD_ID"
DEFAULT_CREDENTIALS_BOARD_ID = "7591024769"
ENV_CREDENTIALS_GROUP_NAME = "MONDAY_CREDENTIALS_GROUP_NAME"


@dataclass(frozen=True)
class PortalCredentialsRecord:
    elemento: str
    login: str
    password: str
    portal_url: str | None
    monday_item_id: str


def get_credentials_board_id_from_env() -> str:
    board_id = os.environ.get(ENV_CREDENTIALS_BOARD_ID, DEFAULT_CREDENTIALS_BOARD_ID).strip()
    return board_id or DEFAULT_CREDENTIALS_BOARD_ID


def get_credentials_group_name_from_env() -> str:
    group_name = os.environ.get(ENV_CREDENTIALS_GROUP_NAME, DEFAULT_CREDENTIALS_GROUP_NAME).strip()
    return group_name or DEFAULT_CREDENTIALS_GROUP_NAME


def _build_column_lookup(columns: list[MondayColumn]) -> dict[str, str]:
    return {column.id: resolve_field_for_column(column.title) or "" for column in columns}


def _extract_record_from_item(
    item: dict,
    *,
    column_lookup: dict[str, str],
) -> PortalCredentialsRecord | None:
    values: dict[str, str | None] = {
        "login": None,
        "password": None,
        "link": None,
    }

    for column_value in item.get("column_values", []):
        field = column_lookup.get(column_value.get("id", ""), "")
        if field not in values:
            continue
        text = (column_value.get("text") or "").strip()
        if field == "link":
            values[field] = parse_link_column_value(column_value.get("value")) or text or None
        else:
            values[field] = text or None

    login = values.get("login")
    password = values.get("password")
    if not login or not password:
        return None

    elemento = str(item.get("name", "")).strip()
    if not elemento:
        return None

    return PortalCredentialsRecord(
        elemento=elemento,
        login=login,
        password=password,
        portal_url=values.get("link"),
        monday_item_id=str(item["id"]),
    )


def fetch_procon_credentials_records(
    *,
    api_token: str,
    board_id: str | None = None,
    group_name: str | None = None,
    limit: int = 50,
) -> list[PortalCredentialsRecord]:
    """Lista credenciais do grupo Procon no board Acessos."""
    resolved_board_id = board_id or get_credentials_board_id_from_env()
    target_group_name = normalize_label(group_name or get_credentials_group_name_from_env())

    data = _graphql_request(
        api_token=api_token,
        query="""
        query ($boardId: [ID!], $limit: Int!) {
          boards(ids: $boardId) {
            columns {
              id
              title
              type
            }
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
        variables={"boardId": resolved_board_id, "limit": limit},
    )

    boards = data.get("boards", [])
    if not boards:
        raise MondayClientError(f'Board de credenciais "{resolved_board_id}" não encontrado.')

    board = boards[0]
    columns = [
        MondayColumn(id=column["id"], title=column["title"], column_type=column["type"])
        for column in board.get("columns", [])
    ]
    column_lookup = _build_column_lookup(columns)

    target_group = None
    for group in board.get("groups", []):
        if normalize_label(group.get("title", "")) == target_group_name:
            target_group = group
            break

    if target_group is None:
        raise MondayClientError(
            f'Grupo "{group_name or get_credentials_group_name_from_env()}" '
            f'não encontrado no board de credenciais.',
        )

    records: list[PortalCredentialsRecord] = []
    for item in target_group.get("items_page", {}).get("items", []):
        record = _extract_record_from_item(item, column_lookup=column_lookup)
        if record is not None:
            records.append(record)
    return records


def find_credentials_for_source(
    records: list[PortalCredentialsRecord],
    *,
    source_id: str,
) -> PortalCredentialsRecord | None:
    for record in records:
        if elemento_matches_source(record.elemento, source_id):
            return record
    return None


def to_portal_credentials(
    record: PortalCredentialsRecord,
    *,
    source_id: str,
) -> PortalCredentials:
    portal_url = record.portal_url or default_portal_url(source_id)
    return PortalCredentials(
        source_id=source_id,
        elemento=record.elemento,
        login=record.login,
        password=record.password,
        portal_url=portal_url,
        monday_item_id=record.monday_item_id,
    )
