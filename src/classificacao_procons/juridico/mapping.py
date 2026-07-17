"""Mapeamento de colunas do Monday para o board jurídico (por título)."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any

from classificacao_procons.monday.mapping import (
    MondayColumn,
    format_column_value,
)

FIELD_PROCESSO = "process_number"
FIELD_TRIBUNAL = "tribunal"
FIELD_VARA = "vara"
FIELD_TIPO = "tipo"
FIELD_PROVIDENCIA = "providencia"
FIELD_PRAZO_FINAL = "prazo_final"
FIELD_AUDIENCIA = "audiencia"
FIELD_STATUS = "status"
FIELD_PARTES = "partes"
FIELD_LINK = "link"

# Ordem importa: campos mais específicos primeiro para evitar colisão de palavras.
FIELD_TITLE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (FIELD_PROCESSO, ("processo", "cnj", "autos", "numero unico")),
    (FIELD_AUDIENCIA, ("audiencia", "data da audiencia", "sessao")),
    (FIELD_PRAZO_FINAL, ("prazo final", "prazo fatal", "prazo", "vencimento")),
    (FIELD_PROVIDENCIA, ("providencia", "provid", "tarefa", "acao")),
    (FIELD_TIPO, ("tipo", "movimento", "classificacao")),
    (FIELD_STATUS, ("status", "situacao")),
    (FIELD_TRIBUNAL, ("tribunal", "comarca", "foro", "orgao")),
    (FIELD_VARA, ("vara", "juizo", "juizado")),
    (FIELD_PARTES, ("partes", "autor", "reu", "reclamante", "reclamado")),
    (FIELD_LINK, ("link", "portal", "url")),
)


def _normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


def resolve_field_for_column(title: str) -> str | None:
    """Associa uma coluna do board jurídico a um campo do domínio pelo título."""
    normalized = _normalize_title(title)
    if not normalized:
        return None
    for field, keywords in FIELD_TITLE_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return field
    return None


def find_column_by_field(columns: list[MondayColumn], field: str) -> MondayColumn | None:
    for column in columns:
        if resolve_field_for_column(column.title) == field:
            return column
    return None


def _format_hearing_value(column_type: str, value: datetime) -> Any:
    if column_type == "date":
        return {"date": value.date().isoformat(), "time": value.strftime("%H:%M")}
    return value.strftime("%d/%m/%Y %H:%M")


def build_providencia_column_values(
    columns: list[MondayColumn],
    *,
    process_number: str,
    tribunal: str | None,
    vara: str | None,
    tipo: str,
    providencia: str,
    prazo_final: date | None,
    hearing_at: datetime | None,
    status: str,
    partes: str | None,
    link: str | None,
) -> dict[str, Any]:
    """Monta os valores de colunas para registrar/atualizar uma providência."""
    values: dict[str, object] = {
        FIELD_PROCESSO: process_number,
        FIELD_TRIBUNAL: tribunal,
        FIELD_VARA: vara,
        FIELD_TIPO: tipo,
        FIELD_PROVIDENCIA: providencia,
        FIELD_PRAZO_FINAL: prazo_final,
        FIELD_AUDIENCIA: hearing_at,
        FIELD_STATUS: status,
        FIELD_PARTES: partes,
        FIELD_LINK: link,
    }

    column_values: dict[str, Any] = {}
    for column in columns:
        field = resolve_field_for_column(column.title)
        if field is None:
            continue
        raw_value = values.get(field)
        if raw_value in (None, ""):
            continue

        if field == FIELD_AUDIENCIA and isinstance(raw_value, datetime):
            column_values[column.id] = _format_hearing_value(column.column_type, raw_value)
            continue

        link_text = "Andamento" if field == FIELD_LINK else "Documento"
        column_values[column.id] = format_column_value(
            column.column_type,
            raw_value,
            link_text=link_text,
        )

    return column_values
