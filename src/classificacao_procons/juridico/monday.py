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
    MondayClientError,
    MondayRegistrationResult,
    _apply_complaint_column_values,
    _build_item_url,
    _create_item,
    _find_existing_item_id,
    _load_board_context,
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
DEFAULT_JURIDICO_BOARD_NAME = "processos"
DEFAULT_JURIDICO_GROUP_NAME = "providencias pendentes"

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


def _normalize_title(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


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
    """Cria item no board jurídico com prazo fatal e audiência. Retorna None sem token."""
    token = api_token or get_api_token_from_env()
    if not token:
        return None

    context = _load_board_context(
        api_token=token,
        board_name=board_name or get_juridico_board_name_from_env(),
        group_name=group_name or get_juridico_group_name_from_env(),
        board_id=get_juridico_board_id_from_env(),
    )

    intimacao_id_column = _find_intimacao_id_column(context.columns)
    if intimacao_id_column is not None:
        existing_item_id = _find_existing_item_id(
            api_token=token,
            board_id=context.board_id,
            protocol_column=intimacao_id_column,
            protocol_number=message_id,
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
        build_providencia_column_values(
            context.columns,
            intimacao=intimacao,
            providencia=providencia,
            message_id=message_id,
            analysis=analysis,
        ),
    )

    item_name = f"{intimacao.process_number} — {providencia.description}"
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
    return MondayRegistrationResult(
        item_id=item_id,
        board_id=context.board_id,
        item_url=_build_item_url(
            account_slug=context.account_slug,
            board_id=context.board_id,
            item_id=item_id,
        ),
    )


__all__ = [
    "MondayClientError",
    "build_providencia_column_values",
    "register_providencia",
    "resolve_juridico_field_for_column",
]
