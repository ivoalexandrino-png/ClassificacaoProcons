"""Cliente GraphQL do Monday.com."""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from classificacao_procons.models import ProcessedComplaint
from classificacao_procons.monday.mapping import (
    MondayColumn,
    MondayColumnDetails,
    build_column_values,
    build_response_column_values,
    find_protocol_column,
    sanitize_column_values,
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
GRAPHQL_MAX_RETRIES = 3
GRAPHQL_RETRY_BASE_DELAY_SECONDS = 2


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
    column_details: list[MondayColumnDetails]
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


def _is_transient_monday_error(exc: MondayClientError) -> bool:
    message = str(exc).casefold()
    return "internal server error" in message or "http 500" in message or "http 502" in message


def _graphql_request(
    *,
    api_token: str,
    query: str,
    variables: dict | None = None,
    max_retries: int = GRAPHQL_MAX_RETRIES,
) -> dict:
    last_error: MondayClientError | None = None

    for attempt in range(max_retries):
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
            last_error = MondayClientError(f"Monday API HTTP {exc.code}: {error_body}")
            if exc.code in {500, 502, 503, 504} and attempt < max_retries - 1:
                time.sleep(GRAPHQL_RETRY_BASE_DELAY_SECONDS * (2**attempt))
                continue
            raise last_error from exc
        except urllib.error.URLError as exc:
            raise MondayClientError(f"Monday API indisponível: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise MondayClientError("Monday API retornou resposta inválida.") from exc

        if body.get("errors"):
            messages = "; ".join(str(item.get("message", item)) for item in body["errors"])
            last_error = MondayClientError(messages)
            if _is_transient_monday_error(last_error) and attempt < max_retries - 1:
                time.sleep(GRAPHQL_RETRY_BASE_DELAY_SECONDS * (2**attempt))
                continue
            raise last_error

        data = body.get("data")
        if not isinstance(data, dict):
            raise MondayClientError("Monday API retornou payload vazio.")

        return data

    if last_error is not None:
        raise last_error
    raise MondayClientError("Monday API retornou payload vazio.")


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
    return [detail.column for detail in _board_column_details(board)]


def _board_column_details(board: dict) -> list[MondayColumnDetails]:
    return [
        MondayColumnDetails(
            column=MondayColumn(
                id=column["id"],
                title=column["title"],
                column_type=column["type"],
            ),
            settings_str=column.get("settings_str"),
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
                  settings_str
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
                  settings_str
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
        column_details=_board_column_details(board),
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
        column_details=_board_column_details(board),
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


def _create_item(
    *,
    api_token: str,
    board_id: str,
    group_id: str,
    item_name: str,
) -> str:
    data = _graphql_request(
        api_token=api_token,
        query="""
        mutation ($boardId: ID!, $groupId: String!, $itemName: String!) {
          create_item(
            board_id: $boardId
            group_id: $groupId
            item_name: $itemName
          ) {
            id
          }
        }
        """,
        variables={
            "boardId": board_id,
            "groupId": group_id,
            "itemName": item_name,
        },
    )
    return str(data["create_item"]["id"])


def _apply_complaint_column_values(
    *,
    api_token: str,
    board_id: str,
    item_id: str,
    column_details: list[MondayColumnDetails],
    column_values: dict[str, object],
    protocol_column_id: str | None = None,
) -> None:
    """Aplica colunas uma a uma para evitar falhas em create_item com payload grande."""
    details_by_id = {detail.column.id: detail for detail in column_details}
    applied_count = 0
    protocol_applied = protocol_column_id is None

    for column_id, value in column_values.items():
        if details_by_id.get(column_id) is None:
            continue
        try:
            _graphql_request(
                api_token=api_token,
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
                    "boardId": board_id,
                    "itemId": item_id,
                    "columnValues": json.dumps({column_id: value}),
                },
            )
        except MondayClientError as exc:
            if column_id == protocol_column_id:
                raise MondayClientError(
                    f"Item {item_id} criado, mas falhou ao preencher protocolo CIP/FA: {exc}",
                ) from exc
            continue

        applied_count += 1
        if column_id == protocol_column_id:
            protocol_applied = True

    if column_values and applied_count == 0:
        raise MondayClientError(
            f"Item {item_id} criado, mas nenhuma coluna foi preenchida no Monday.",
        )

    if protocol_column_id is not None and not protocol_applied:
        raise MondayClientError(
            f"Item {item_id} criado, mas coluna de protocolo CIP/FA não foi preenchida.",
        )


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

    column_values = sanitize_column_values(
        context.column_details,
        build_column_values(
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
        ),
    )

    item_id = _create_item(
        api_token=token,
        board_id=context.board_id,
        group_id=context.group_id,
        item_name=complaint.consumer_name,
    )
    _apply_complaint_column_values(
        api_token=token,
        board_id=context.board_id,
        item_id=item_id,
        column_details=context.column_details,
        column_values=column_values,
        protocol_column_id=protocol_column.id if protocol_column is not None else None,
    )
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
