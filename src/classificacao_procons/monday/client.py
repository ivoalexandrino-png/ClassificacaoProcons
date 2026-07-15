"""Cliente GraphQL do Monday.com."""

from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass

from classificacao_procons.models import ProcessedComplaint
from classificacao_procons.monday.mapping import (
    MondayColumn,
    build_column_values,
    find_protocol_column,
)

MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_API_VERSION = "2024-10"
DEFAULT_BOARD_NAME = "procons"
DEFAULT_GROUP_NAME = "pendentes de resposta"
ENV_API_TOKEN = "MONDAY_API_TOKEN"


class MondayClientError(RuntimeError):
    """Erro ao registrar reclamação no Monday.com."""


@dataclass(frozen=True)
class MondayRegistrationResult:
    item_id: str
    board_id: str
    item_url: str | None = None
    skipped_duplicate: bool = False


@dataclass(frozen=True)
class MondayBoardContext:
    board_id: str
    group_id: str
    columns: list[MondayColumn]
    account_slug: str | None = None


def get_api_token_from_env() -> str | None:
    token = os.environ.get(ENV_API_TOKEN, "").strip()
    return token or None


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


def _graphql_request(*, api_token: str, query: str, variables: dict | None = None) -> dict:
    payload: dict[str, object] = {"query": query}
    if variables:
        payload["variables"] = variables

    request = urllib.request.Request(
        MONDAY_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": api_token,
            "Content-Type": "application/json",
            "API-Version": MONDAY_API_VERSION,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise MondayClientError(f"Monday API HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise MondayClientError(f"Monday API indisponível: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise MondayClientError("Monday API retornou resposta inválida.") from exc

    if body.get("errors"):
        messages = "; ".join(str(item.get("message", item)) for item in body["errors"])
        raise MondayClientError(messages)

    data = body.get("data")
    if not isinstance(data, dict):
        raise MondayClientError("Monday API retornou payload vazio.")

    return data


def _load_board_context(
    *,
    api_token: str,
    board_name: str,
    group_name: str,
) -> MondayBoardContext:
    data = _graphql_request(
        api_token=api_token,
        query="""
        query {
          me {
            account {
              slug
            }
          }
          boards(limit: 200) {
            id
            name
            groups {
              id
              title
            }
            columns {
              id
              title
              type
            }
          }
        }
        """,
    )

    account = data.get("me", {}).get("account", {})
    account_slug = account.get("slug") if isinstance(account, dict) else None

    boards = data.get("boards", [])
    target_board_name = _normalize_name(board_name)
    target_group_name = _normalize_name(group_name)

    for board in boards:
        if _normalize_name(board.get("name", "")) != target_board_name:
            continue

        group_id = None
        for group in board.get("groups", []):
            if _normalize_name(group.get("title", "")) == target_group_name:
                group_id = group["id"]
                break

        if group_id is None:
            raise MondayClientError(
                f'Grupo "{group_name}" não encontrado no board "{board_name}".',
            )

        columns = [
            MondayColumn(
                id=column["id"],
                title=column["title"],
                column_type=column["type"],
            )
            for column in board.get("columns", [])
        ]

        return MondayBoardContext(
            board_id=str(board["id"]),
            group_id=group_id,
            columns=columns,
            account_slug=account_slug,
        )

    raise MondayClientError(f'Board "{board_name}" não encontrado no Monday.com.')


def _find_existing_item_id(
    *,
    api_token: str,
    board_id: str,
    protocol_column: MondayColumn,
    protocol_number: str,
) -> str | None:
    data = _graphql_request(
        api_token=api_token,
        query="""
        query ($boardId: ID!, $columnId: String!, $value: String!) {
          items_page_by_column_values(
            board_id: $boardId
            columns: [{column_id: $columnId, column_values: [$value]}]
            limit: 1
          ) {
            items {
              id
            }
          }
        }
        """,
        variables={
            "boardId": board_id,
            "columnId": protocol_column.id,
            "value": protocol_number,
        },
    )

    items = data.get("items_page_by_column_values", {}).get("items", [])
    if not items:
        return None
    return str(items[0]["id"])


def _build_item_url(
    *,
    account_slug: str | None,
    board_id: str,
    item_id: str,
) -> str | None:
    if not account_slug:
        return None
    return f"https://{account_slug}.monday.com/boards/{board_id}/pulses/{item_id}"


def register_complaint(
    complaint: ProcessedComplaint,
    *,
    api_token: str | None = None,
    board_name: str = DEFAULT_BOARD_NAME,
    group_name: str = DEFAULT_GROUP_NAME,
) -> MondayRegistrationResult | None:
    """Cadastra reclamação processada no Monday.com."""
    token = api_token or get_api_token_from_env()
    if not token:
        return None

    if complaint.status != "success":
        raise MondayClientError("Só é possível cadastrar reclamações processadas com sucesso.")

    context = _load_board_context(
        api_token=token,
        board_name=board_name,
        group_name=group_name,
    )

    protocol_column = find_protocol_column(context.columns)
    if protocol_column is not None:
        existing_item_id = _find_existing_item_id(
            api_token=token,
            board_id=context.board_id,
            protocol_column=protocol_column,
            protocol_number=complaint.protocol_number,
        )
        if existing_item_id is not None:
            return MondayRegistrationResult(
                item_id=existing_item_id,
                board_id=context.board_id,
                item_url=_build_item_url(
                    account_slug=context.account_slug,
                    board_id=context.board_id,
                    item_id=existing_item_id,
                ),
                skipped_duplicate=True,
            )

    column_values = build_column_values(
        context.columns,
        consumer_name=complaint.consumer_name,
        state=complaint.state,
        pdf_url=complaint.pdf_url,
        protocol_number=complaint.protocol_number,
        consumer_cpf=complaint.consumer_cpf,
        complaint_date=complaint.complaint_date,
        sac_deadline=complaint.sac_deadline,
        legal_deadline=complaint.legal_deadline,
        cause=complaint.cause,
    )

    data = _graphql_request(
        api_token=token,
        query="""
        mutation ($boardId: ID!, $groupId: String!, $itemName: String!, $columnValues: JSON) {
          create_item(
            board_id: $boardId
            group_id: $groupId
            item_name: $itemName
            column_values: $columnValues
          ) {
            id
          }
        }
        """,
        variables={
            "boardId": context.board_id,
            "groupId": context.group_id,
            "itemName": complaint.consumer_name,
            "columnValues": json.dumps(column_values),
        },
    )

    item_id = str(data["create_item"]["id"])
    return MondayRegistrationResult(
        item_id=item_id,
        board_id=context.board_id,
        item_url=_build_item_url(
            account_slug=context.account_slug,
            board_id=context.board_id,
            item_id=item_id,
        ),
    )
