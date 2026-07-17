"""Cadastro de providências jurídicas no Monday.com (prazos e audiências)."""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime
from typing import Any

from classificacao_procons.juridico.models import (
    NOTIFICATION_TYPE_AUDIENCIA,
    NOTIFICATION_TYPE_CITACAO,
    NOTIFICATION_TYPE_DECISAO,
    NOTIFICATION_TYPE_INTIMACAO,
    NOTIFICATION_TYPE_SENTENCA,
    ParsedIntimacao,
    Providencia,
)
from classificacao_procons.monday.client import (
    MondayBoardContext,
    MondayClientError,
    MondayRegistrationResult,
    _apply_complaint_column_values,
    _board_column_details,
    _board_columns,
    _build_item_url,
    _create_item,
    _fetch_board_record,
    _find_existing_item_id,
    _graphql_request,
    get_api_token_from_env,
)
from classificacao_procons.monday.mapping import (
    MondayColumn,
    format_column_value,
    sanitize_column_values,
)

ENV_JURIDICO_BOARD_NAME = "MONDAY_JURIDICO_BOARD_NAME"
ENV_JURIDICO_BOARD_ID = "MONDAY_JURIDICO_BOARD_ID"
ENV_JURIDICO_GROUP_NAME = "MONDAY_JURIDICO_GROUP_NAME"
DEFAULT_JURIDICO_BOARD_NAME = "prazos"
DEFAULT_JURIDICO_GROUP_NAME = ""

ENV_AUDIENCIAS_BOARD_NAME = "MONDAY_AUDIENCIAS_BOARD_NAME"
ENV_AUDIENCIAS_BOARD_ID = "MONDAY_AUDIENCIAS_BOARD_ID"
ENV_AUDIENCIAS_GROUP_NAME = "MONDAY_AUDIENCIAS_GROUP_NAME"
DEFAULT_AUDIENCIAS_BOARD_NAME = "audiencias"
DEFAULT_AUDIENCIAS_GROUP_NAME = ""

FIELD_INTIMACAO_ID = "intimacao_id"
FIELD_PROCESS_NUMBER = "process_number"
FIELD_TRIBUNAL = "tribunal"
FIELD_COURT_UNIT = "court_unit"
FIELD_NOTIFICATION_TYPE = "notification_type"
FIELD_PROVIDENCIA = "providencia"
FIELD_DUE_DATE = "due_date"
FIELD_HEARING = "hearing_datetime"
FIELD_SUMMARY = "summary"
FIELD_ANALYSIS = "analysis"

_FIELD_TITLE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (FIELD_INTIMACAO_ID, ("id intimacao", "id da intimacao", "message id")),
    (FIELD_DUE_DATE, ("prazo fatal", "prazo final", "prazo")),
    (FIELD_HEARING, ("audiencia",)),
    (FIELD_PROVIDENCIA, ("providencia", "acao necessaria")),
    (FIELD_ANALYSIS, ("analise", "o que aconteceu", "parecer", "entendimento")),
    (FIELD_NOTIFICATION_TYPE, ("tipo de intimacao", "tipo intimacao", "tipo")),
    (FIELD_PROCESS_NUMBER, ("numero do processo", "processo", "cnj")),
    (FIELD_TRIBUNAL, ("tribunal",)),
    (FIELD_COURT_UNIT, ("vara", "juizado", "comarca", "orgao")),
    (FIELD_SUMMARY, ("teor", "resumo", "descricao")),
)

NOTIFICATION_TYPE_LABELS: dict[str, str] = {
    NOTIFICATION_TYPE_CITACAO: "Citação",
    NOTIFICATION_TYPE_INTIMACAO: "Intimação",
    NOTIFICATION_TYPE_AUDIENCIA: "Audiência",
    NOTIFICATION_TYPE_SENTENCA: "Sentença",
    NOTIFICATION_TYPE_DECISAO: "Decisão/Despacho",
}


def get_juridico_board_name_from_env() -> str:
    board_name = os.environ.get(ENV_JURIDICO_BOARD_NAME, "").strip()
    return board_name or DEFAULT_JURIDICO_BOARD_NAME


def get_juridico_board_id_from_env() -> str | None:
    board_id = os.environ.get(ENV_JURIDICO_BOARD_ID, "").strip()
    return board_id or None


def get_juridico_group_name_from_env() -> str:
    group_name = os.environ.get(ENV_JURIDICO_GROUP_NAME, "").strip()
    return group_name or DEFAULT_JURIDICO_GROUP_NAME


def get_audiencias_board_name_from_env() -> str:
    board_name = os.environ.get(ENV_AUDIENCIAS_BOARD_NAME, "").strip()
    return board_name or DEFAULT_AUDIENCIAS_BOARD_NAME


def get_audiencias_board_id_from_env() -> str | None:
    board_id = os.environ.get(ENV_AUDIENCIAS_BOARD_ID, "").strip()
    return board_id or None


def get_audiencias_group_name_from_env() -> str:
    group_name = os.environ.get(ENV_AUDIENCIAS_GROUP_NAME, "").strip()
    return group_name or DEFAULT_AUDIENCIAS_GROUP_NAME


def _normalize_title(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


_BOARDS_PAGE_QUERY = """
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
"""

_BOARD_PAGE_SIZE = 100
_MAX_BOARD_PAGES = 20


def _list_all_boards(api_token: str) -> list[dict]:
    boards: list[dict] = []
    for page in range(1, _MAX_BOARD_PAGES + 1):
        data = _graphql_request(
            api_token=api_token,
            query=_BOARDS_PAGE_QUERY,
            variables={"limit": _BOARD_PAGE_SIZE, "page": page},
        )
        page_boards = data.get("boards", [])
        if not page_boards:
            break
        boards.extend(page_boards)
        if len(page_boards) < _BOARD_PAGE_SIZE:
            break
    return boards


def _pick_juridico_board(boards: list[dict], board_name: str) -> dict | None:
    """Match exato pelo nome normalizado; senão, board cujo nome contém o alvo."""
    target = _normalize_title(board_name)
    for board in boards:
        if _normalize_title(str(board.get("name", ""))) == target:
            return board
    for board in boards:
        if target in _normalize_title(str(board.get("name", ""))):
            return board
    return None


def _account_slug(api_token: str) -> str | None:
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
    return account.get("slug") if isinstance(account, dict) else None


def _load_juridico_board_context(
    *,
    api_token: str,
    board_name: str,
    board_id: str | None,
    group_name: str,
) -> MondayBoardContext:
    """Carrega o board; se o grupo configurado não existir, usa o primeiro grupo."""
    if board_id:
        board = _fetch_board_record(
            api_token=api_token,
            board_name=board_name,
            board_id=board_id,
        )
    else:
        boards = _list_all_boards(api_token)
        board = _pick_juridico_board(boards, board_name)
        if board is None:
            visible = ", ".join(
                sorted({str(item.get("name", "")) for item in boards if item.get("name")}),
            )
            raise MondayClientError(
                f'Board "{board_name}" não encontrado no Monday.com. '
                f"Boards visíveis para este token: {visible or '(nenhum)'}.",
            )

    groups = board.get("groups", [])
    if not groups:
        raise MondayClientError(
            f'Board "{board.get("name", board_name)}" não tem grupos no Monday.com.',
        )

    group_id = None
    if group_name:
        target_group = _normalize_title(group_name)
        for group in groups:
            if _normalize_title(str(group.get("title", ""))) == target_group:
                group_id = group["id"]
                break
    if group_id is None:
        group_id = groups[0]["id"]

    return MondayBoardContext(
        board_id=str(board["id"]),
        group_id=group_id,
        columns=_board_columns(board),
        column_details=_board_column_details(board),
        account_slug=_account_slug(api_token),
    )


def resolve_juridico_field_for_column(title: str) -> str | None:
    """Associa uma coluna do board jurídico a um campo do domínio pelo título."""
    normalized = _normalize_title(title)
    for field, keywords in _FIELD_TITLE_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return field
    return None


def _hearing_column_value(hearing: datetime) -> dict[str, str]:
    value: dict[str, str] = {"date": hearing.date().isoformat()}
    if (hearing.hour, hearing.minute) != (0, 0):
        value["time"] = hearing.strftime("%H:%M:%S")
    return value


def build_providencia_column_values(
    columns: list[MondayColumn],
    *,
    intimacao: ParsedIntimacao,
    providencia: Providencia,
    message_id: str,
    analysis: str | None = None,
) -> dict[str, Any]:
    """Monta valores de colunas do board jurídico a partir da triagem."""
    values: dict[str, Any] = {
        FIELD_INTIMACAO_ID: message_id,
        FIELD_PROCESS_NUMBER: intimacao.process_number,
        FIELD_TRIBUNAL: intimacao.tribunal,
        FIELD_COURT_UNIT: intimacao.court_unit,
        FIELD_NOTIFICATION_TYPE: NOTIFICATION_TYPE_LABELS.get(intimacao.notification_type),
        FIELD_PROVIDENCIA: providencia.description,
        FIELD_DUE_DATE: providencia.due_date,
        FIELD_SUMMARY: intimacao.summary,
        FIELD_ANALYSIS: analysis,
    }

    column_values: dict[str, Any] = {}
    for column in columns:
        field = resolve_juridico_field_for_column(column.title)
        if field is None:
            continue

        if field == FIELD_HEARING:
            if providencia.hearing_datetime is not None:
                column_values[column.id] = _hearing_column_value(providencia.hearing_datetime)
            continue

        raw_value = values.get(field)
        if raw_value in (None, ""):
            continue
        column_values[column.id] = format_column_value(column.column_type, raw_value)

    return column_values


def _find_intimacao_id_column(columns: list[MondayColumn]) -> MondayColumn | None:
    for column in columns:
        if resolve_juridico_field_for_column(column.title) == FIELD_INTIMACAO_ID:
            return column
    return None


def _create_item_with_dedupe(
    *,
    api_token: str,
    context: MondayBoardContext,
    item_name: str,
    column_values: dict[str, Any],
    dedupe_value: str,
) -> MondayRegistrationResult:
    """Cria item no board, pulando quando a intimação já foi cadastrada."""
    intimacao_id_column = _find_intimacao_id_column(context.columns)
    if intimacao_id_column is not None:
        existing_item_id = _find_existing_item_id(
            api_token=api_token,
            board_id=context.board_id,
            protocol_column=intimacao_id_column,
            protocol_number=dedupe_value,
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

    item_id = _create_item(
        api_token=api_token,
        board_id=context.board_id,
        group_id=context.group_id,
        item_name=item_name,
    )
    _apply_complaint_column_values(
        api_token=api_token,
        board_id=context.board_id,
        item_id=item_id,
        column_details=context.column_details,
        column_values=column_values,
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


def register_providencia(
    *,
    intimacao: ParsedIntimacao,
    providencia: Providencia,
    message_id: str,
    analysis: str | None = None,
    api_token: str | None = None,
    board_name: str | None = None,
    group_name: str | None = None,
) -> MondayRegistrationResult | None:
    """Cria item no board de prazos com prazo fatal e análise. Retorna None sem token."""
    token = api_token or get_api_token_from_env()
    if not token:
        return None

    context = _load_juridico_board_context(
        api_token=token,
        board_name=board_name or get_juridico_board_name_from_env(),
        board_id=get_juridico_board_id_from_env(),
        group_name=group_name if group_name is not None else get_juridico_group_name_from_env(),
    )
    column_values = sanitize_column_values(
        context.column_details,
        build_providencia_column_values(
            context.columns,
            intimacao=intimacao,
            providencia=providencia,
            message_id=message_id,
            analysis=analysis,
        ),
    )
    return _create_item_with_dedupe(
        api_token=token,
        context=context,
        item_name=f"{intimacao.process_number} — {providencia.description}",
        column_values=column_values,
        dedupe_value=message_id,
    )


def register_audiencia(
    *,
    intimacao: ParsedIntimacao,
    providencia: Providencia,
    message_id: str,
    analysis: str | None = None,
    api_token: str | None = None,
    board_name: str | None = None,
    group_name: str | None = None,
) -> MondayRegistrationResult | None:
    """Cria item no board de audiências quando há audiência marcada.

    Não substitui o item de prazo: um mesmo processo pode ter prazo de
    contestação no board "prazos" e audiência no board "audiências".
    """
    hearing = providencia.hearing_datetime
    if hearing is None:
        return None

    token = api_token or get_api_token_from_env()
    if not token:
        return None

    context = _load_juridico_board_context(
        api_token=token,
        board_name=board_name or get_audiencias_board_name_from_env(),
        board_id=get_audiencias_board_id_from_env(),
        group_name=(
            group_name if group_name is not None else get_audiencias_group_name_from_env()
        ),
    )
    column_values = sanitize_column_values(
        context.column_details,
        build_providencia_column_values(
            context.columns,
            intimacao=intimacao,
            providencia=providencia,
            message_id=message_id,
            analysis=analysis,
        ),
    )
    item_name = f"{intimacao.process_number} — Audiência {hearing.strftime('%d/%m/%Y %H:%M')}"
    return _create_item_with_dedupe(
        api_token=token,
        context=context,
        item_name=item_name,
        column_values=column_values,
        dedupe_value=message_id,
    )


def describe_boards(
    *,
    api_token: str | None = None,
    name_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Lista boards visíveis com grupos e colunas — para calibrar o mapeamento."""
    token = api_token or get_api_token_from_env()
    if not token:
        raise MondayClientError("MONDAY_API_TOKEN não configurada.")

    boards = _list_all_boards(token)
    normalized_filter = _normalize_title(name_filter) if name_filter else None

    described: list[dict[str, Any]] = []
    for board in boards:
        name = str(board.get("name", ""))
        if normalized_filter and normalized_filter not in _normalize_title(name):
            continue
        described.append(
            {
                "id": str(board.get("id", "")),
                "name": name,
                "groups": [str(group.get("title", "")) for group in board.get("groups", [])],
                "columns": [
                    {
                        "title": str(column.get("title", "")),
                        "type": str(column.get("type", "")),
                        "mapped_field": resolve_juridico_field_for_column(
                            str(column.get("title", "")),
                        ),
                    }
                    for column in board.get("columns", [])
                ],
            },
        )
    return described


__all__ = [
    "MondayClientError",
    "build_providencia_column_values",
    "describe_boards",
    "register_audiencia",
    "register_providencia",
    "resolve_juridico_field_for_column",
]
