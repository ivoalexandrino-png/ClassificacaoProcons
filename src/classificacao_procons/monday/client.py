"""Cliente GraphQL do Monday.com."""

from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from classificacao_procons.models import ProcessedComplaint
from classificacao_procons.monday.mapping import (
    MondayColumn,
    build_column_values,
    build_response_column_values,
    find_protocol_column,
)

MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"
MONDAY_API_VERSION = "2024-10"
DEFAULT_BOARD_NAME = "procons"
DEFAULT_GROUP_NAME = "pendentes de resposta"
ENV_API_TOKEN = "MONDAY_API_TOKEN"
ENV_BOARD_NAME = "MONDAY_BOARD_NAME"
ENV_BOARD_ID = "MONDAY_BOARD_ID"
BOARD_PAGE_SIZE = 100
MAX_BOARD_PAGES = 20


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


def get_board_name_from_env() -> str:
    board_name = os.environ.get(ENV_BOARD_NAME, DEFAULT_BOARD_NAME).strip()
    return board_name or DEFAULT_BOARD_NAME


def get_board_id_from_env() -> str | None:
    board_id = os.environ.get(ENV_BOARD_ID, "").strip()
    return board_id or None


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


def upload_file_to_column(
    *,
    api_token: str,
    item_id: str,
    column_id: str,
    file_path: Path,
) -> None:
    """Envia PDF/arquivo para coluna do tipo file no Monday."""
    if not file_path.exists():
        raise MondayClientError(f"Arquivo não encontrado para upload no Monday: {file_path}")

    file_bytes = file_path.read_bytes()
    boundary = f"----MondayFormBoundary{uuid.uuid4().hex}"
    query = (
        "mutation ($file: File!) {"
        f' add_file_to_column(item_id: {item_id}, column_id: "{column_id}", file: $file)'
        " { id } }"
    )
    map_payload = json.dumps({"file": "variables.file"})

    body = bytearray()
    for part_name, part_value in (
        ("query", query),
        ("map", map_payload),
    ):
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{part_name}"\r\n\r\n'.encode())
        body.extend(part_value.encode("utf-8"))
        body.extend(b"\r\n")

    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode(),
    )
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode())

    request = urllib.request.Request(
        MONDAY_FILE_API_URL,
        data=bytes(body),
        headers={
            "Authorization": api_token,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "API-Version": MONDAY_API_VERSION,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise MondayClientError(f"Monday file API HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise MondayClientError(f"Monday file API indisponível: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise MondayClientError("Monday file API retornou resposta inválida.") from exc

    if payload.get("errors"):
        messages = "; ".join(str(item.get("message", item)) for item in payload["errors"])
        raise MondayClientError(messages)


def _board_columns(board: dict) -> list[MondayColumn]:
    return [
        MondayColumn(
            id=column["id"],
            title=column["title"],
            column_type=column["type"],
        )
        for column in board.get("columns", [])
    ]


def _pick_board_by_name(boards: list[dict], board_name: str) -> dict | None:
    target_board_name = _normalize_name(board_name)
    for board in boards:
        if _normalize_name(board.get("name", "")) == target_board_name:
            return board

    for board in boards:
        normalized = _normalize_name(board.get("name", ""))
        if "procon" in normalized:
            return board

    return None


def _fetch_board_record(
    *,
    api_token: str,
    board_name: str,
    board_id: str | None = None,
) -> dict:
    if board_id:
        data = _graphql_request(
            api_token=api_token,
            query="""
            query ($boardId: [ID!]) {
              boards(ids: $boardId) {
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
            variables={"boardId": board_id},
        )
        boards = data.get("boards", [])
        if boards:
            return boards[0]
        raise MondayClientError(f'Board id "{board_id}" não encontrado no Monday.com.')

    collected_boards: list[dict] = []
    for page in range(1, MAX_BOARD_PAGES + 1):
        data = _graphql_request(
            api_token=api_token,
            query="""
            query ($limit: Int!, $page: Int!) {
              boards(limit: $limit, page: $page) {
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
            variables={"limit": BOARD_PAGE_SIZE, "page": page},
        )
        page_boards = data.get("boards", [])
        if not page_boards:
            break
        collected_boards.extend(page_boards)
        if len(page_boards) < BOARD_PAGE_SIZE:
            break

    board = _pick_board_by_name(collected_boards, board_name)
    if board is not None:
        return board

    visible_names = ", ".join(
        sorted({str(item.get("name", "")) for item in collected_boards if item.get("name")}),
    )
    hint = (
        f" Boards visíveis para este token: {visible_names}."
        if visible_names
        else " Nenhum board visível para este token."
    )
    raise MondayClientError(
        f'Board "{board_name}" não encontrado no Monday.com.{hint}',
    )


def _load_board_context(
    *,
    api_token: str,
    board_name: str,
    group_name: str,
    board_id: str | None = None,
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
        }
        """,
    )

    account = data.get("me", {}).get("account", {})
    account_slug = account.get("slug") if isinstance(account, dict) else None

    board = _fetch_board_record(
        api_token=api_token,
        board_name=board_name,
        board_id=board_id,
    )
    target_group_name = _normalize_name(group_name)

    group_id = None
    for group in board.get("groups", []):
        if _normalize_name(group.get("title", "")) == target_group_name:
            group_id = group["id"]
            break

    if group_id is None:
        raise MondayClientError(
            f'Grupo "{group_name}" não encontrado no board "{board.get("name", board_name)}".',
        )

    return MondayBoardContext(
        board_id=str(board["id"]),
        group_id=group_id,
        columns=_board_columns(board),
        account_slug=account_slug,
    )


def load_board_metadata(
    *,
    api_token: str,
    board_name: str | None = None,
    board_id: str | None = None,
) -> MondayBoardContext:
    """Carrega metadados do board sem exigir um grupo específico."""
    resolved_board_name = board_name or get_board_name_from_env()
    resolved_board_id = board_id or get_board_id_from_env()

    data = _graphql_request(
        api_token=api_token,
        query="""
        query {
          me {
            account {
              slug
            }
          }
        }
        """,
    )
    account = data.get("me", {}).get("account", {})
    account_slug = account.get("slug") if isinstance(account, dict) else None

    board = _fetch_board_record(
        api_token=api_token,
        board_name=resolved_board_name,
        board_id=resolved_board_id,
    )

    return MondayBoardContext(
        board_id=str(board["id"]),
        group_id="",
        columns=_board_columns(board),
        account_slug=account_slug,
    )


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
        board_name=board_name or get_board_name_from_env(),
        group_name=group_name,
        board_id=get_board_id_from_env(),
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


def update_elaborated_response_links(
    *,
    item_id: str,
    full_response_url: str,
    summary_response_url: str,
    unified_pdf_url: str | None = None,
    api_token: str | None = None,
    board_name: str | None = None,
) -> None:
    """Atualiza colunas de link com resposta completa, resumo e PDF unificado."""
    token = api_token or get_api_token_from_env()
    if not token:
        raise MondayClientError("MONDAY_API_TOKEN não configurada.")

    context = load_board_metadata(
        api_token=token,
        board_name=board_name or get_board_name_from_env(),
    )
    column_values = build_response_column_values(
        context.columns,
        full_response_url=full_response_url,
        summary_response_url=summary_response_url,
        unified_pdf_url=unified_pdf_url,
    )
    if not column_values:
        raise MondayClientError(
            "Nenhuma coluna de resposta encontrada no Monday. "
            "Crie colunas link: Resposta Completa, Resumo Resposta e PDF Unificado.",
        )

    _graphql_request(
        api_token=token,
        query="""
        mutation ($boardId: ID!, $itemId: ID!, $columnValues: JSON!) {
          change_multiple_column_values(
            board_id: $boardId
            item_id: $itemId
            column_values: $columnValues
          ) {
            id
          }
        }
        """,
        variables={
            "boardId": context.board_id,
            "itemId": item_id,
            "columnValues": json.dumps(column_values),
        },
    )
