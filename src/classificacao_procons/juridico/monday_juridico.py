"""Registro de providências jurídicas no Monday.com (prazos e audiências)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from classificacao_procons.juridico.mapping import (
    FIELD_PROCESSO,
    build_providencia_column_values,
    find_column_by_field,
)
from classificacao_procons.juridico.models import ProcessoJudicial, Providencia
from classificacao_procons.monday.client import (
    BOARD_PAGE_SIZE,
    MAX_BOARD_PAGES,
    MondayBoardContext,
    MondayClientError,
    _apply_complaint_column_values,
    _board_column_details,
    _board_columns,
    _build_item_url,
    _create_item,
    _find_existing_item_id,
    _graphql_request,
    _normalize_name,
)
from classificacao_procons.monday.mapping import sanitize_column_values

DEFAULT_BOARD_NAME = "juridico"
DEFAULT_GROUP_NAME = "prazos e audiencias"
ENV_API_TOKEN = "MONDAY_API_TOKEN"
ENV_BOARD_NAME = "JURIDICO_MONDAY_BOARD_NAME"
ENV_BOARD_ID = "JURIDICO_MONDAY_BOARD_ID"
ENV_GROUP_NAME = "JURIDICO_MONDAY_GROUP_NAME"

_BOARD_FALLBACK_KEYWORDS = ("juridic", "processo", "prazo")


@dataclass(frozen=True)
class ProvidenciaRegistrationResult:
    item_id: str
    board_id: str
    item_url: str | None = None
    skipped_duplicate: bool = False


def get_api_token_from_env() -> str | None:
    token = os.environ.get(ENV_API_TOKEN, "").strip()
    return token or None


def get_board_name_from_env() -> str:
    return os.environ.get(ENV_BOARD_NAME, DEFAULT_BOARD_NAME).strip() or DEFAULT_BOARD_NAME


def get_board_id_from_env() -> str | None:
    return os.environ.get(ENV_BOARD_ID, "").strip() or None


def get_group_name_from_env() -> str:
    return os.environ.get(ENV_GROUP_NAME, DEFAULT_GROUP_NAME).strip() or DEFAULT_GROUP_NAME


_BOARD_QUERY_BY_ID = """
query ($boardId: [ID!]) {
  boards(ids: $boardId) {
    id
    name
    groups { id title }
    columns { id title type settings_str }
  }
}
"""

_BOARD_QUERY_PAGE = """
query ($limit: Int!, $page: Int!) {
  boards(limit: $limit, page: $page) {
    id
    name
    groups { id title }
    columns { id title type settings_str }
  }
}
"""


def _pick_juridico_board(boards: list[dict], board_name: str) -> dict | None:
    target = _normalize_name(board_name)
    for board in boards:
        if _normalize_name(board.get("name", "")) == target:
            return board
    for board in boards:
        normalized = _normalize_name(board.get("name", ""))
        if any(keyword in normalized for keyword in _BOARD_FALLBACK_KEYWORDS):
            return board
    return None


def _fetch_board_record(*, api_token: str, board_name: str, board_id: str | None) -> dict:
    if board_id:
        data = _graphql_request(
            api_token=api_token,
            query=_BOARD_QUERY_BY_ID,
            variables={"boardId": board_id},
        )
        boards = data.get("boards", [])
        if boards:
            return boards[0]
        raise MondayClientError(f'Board id "{board_id}" não encontrado no Monday.com.')

    collected: list[dict] = []
    for page in range(1, MAX_BOARD_PAGES + 1):
        data = _graphql_request(
            api_token=api_token,
            query=_BOARD_QUERY_PAGE,
            variables={"limit": BOARD_PAGE_SIZE, "page": page},
        )
        page_boards = data.get("boards", [])
        if not page_boards:
            break
        collected.extend(page_boards)
        if len(page_boards) < BOARD_PAGE_SIZE:
            break

    board = _pick_juridico_board(collected, board_name)
    if board is not None:
        return board

    visible = ", ".join(sorted({str(b.get("name", "")) for b in collected if b.get("name")}))
    hint = f" Boards visíveis: {visible}." if visible else " Nenhum board visível para este token."
    raise MondayClientError(f'Board "{board_name}" não encontrado no Monday.com.{hint}')


def _load_board_context(
    *,
    api_token: str,
    board_name: str,
    group_name: str,
    board_id: str | None = None,
) -> MondayBoardContext:
    data = _graphql_request(
        api_token=api_token,
        query="query { me { account { slug } } }",
    )
    account = data.get("me", {}).get("account", {})
    account_slug = account.get("slug") if isinstance(account, dict) else None

    board = _fetch_board_record(api_token=api_token, board_name=board_name, board_id=board_id)

    target_group = _normalize_name(group_name)
    group_id = None
    for group in board.get("groups", []):
        if _normalize_name(group.get("title", "")) == target_group:
            group_id = group["id"]
            break
    if group_id is None:
        groups = board.get("groups", [])
        if groups:
            group_id = groups[0]["id"]
        else:
            raise MondayClientError(
                f'Nenhum grupo encontrado no board "{board.get("name", board_name)}".',
            )

    return MondayBoardContext(
        board_id=str(board["id"]),
        group_id=group_id,
        columns=_board_columns(board),
        column_details=_board_column_details(board),
        account_slug=account_slug,
    )


def register_providencia(
    providencia: Providencia,
    processo: ProcessoJudicial,
    *,
    api_token: str | None = None,
    board_name: str | None = None,
    group_name: str | None = None,
    board_id: str | None = None,
) -> ProvidenciaRegistrationResult | None:
    """Registra uma providência no board jurídico do Monday.

    Retorna ``None`` quando não há token configurado (skip gracioso). Faz
    deduplicação pelo número do processo quando há coluna correspondente.
    """
    token = api_token or get_api_token_from_env()
    if not token:
        return None

    if not providencia.process_number:
        raise MondayClientError("Providência sem número de processo não pode ser registrada.")

    context = _load_board_context(
        api_token=token,
        board_name=board_name or get_board_name_from_env(),
        group_name=group_name or get_group_name_from_env(),
        board_id=board_id or get_board_id_from_env(),
    )

    processo_column = find_column_by_field(context.columns, FIELD_PROCESSO)
    if processo_column is not None:
        existing_item_id = _find_existing_item_id(
            api_token=token,
            board_id=context.board_id,
            protocol_column=processo_column,
            protocol_number=providencia.process_number,
        )
        if existing_item_id is not None:
            return ProvidenciaRegistrationResult(
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
        build_providencia_column_values(
            context.columns,
            process_number=providencia.process_number,
            tribunal=processo.tribunal,
            vara=processo.vara,
            tipo=providencia.tipo,
            providencia=providencia.descricao,
            prazo_final=providencia.prazo_final,
            hearing_at=providencia.hearing_at,
            status=providencia.status,
            partes=processo.parties,
            link=processo.portal_url,
        ),
    )

    item_name = f"{providencia.process_number} — {providencia.tipo}"
    item_id = _create_item(
        api_token=token,
        board_id=context.board_id,
        group_id=context.group_id,
        item_name=item_name,
    )
    _apply_complaint_column_values(
        api_token=token,
        board_id=context.board_id,
        item_id=item_id,
        column_details=context.column_details,
        column_values=column_values,
    )
    return ProvidenciaRegistrationResult(
        item_id=item_id,
        board_id=context.board_id,
        item_url=_build_item_url(
            account_slug=context.account_slug,
            board_id=context.board_id,
            item_id=item_id,
        ),
    )
