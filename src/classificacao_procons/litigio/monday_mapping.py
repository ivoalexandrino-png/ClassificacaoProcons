"""Mapeamento de colunas do board de Litígio/Processos Judiciais no Monday."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from classificacao_procons.litigio.models import EventoProcesso
from classificacao_procons.monday.mapping import (
    MondayColumn,
    format_link_column_value,
)

FIELD_NUMERO_PROCESSO = "numero_processo"
FIELD_TRIBUNAL = "tribunal"
FIELD_TIPO_PROVIDENCIA = "tipo_providencia"
FIELD_PRAZO = "prazo"
FIELD_AUDIENCIA = "data_audiencia"
FIELD_STATUS = "status"
FIELD_RESUMO = "resumo"
FIELD_LINK_CERTIDAO = "link_certidao"
FIELD_LINK_TRIBUNAL = "link_tribunal"

FIELD_TITLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    FIELD_NUMERO_PROCESSO: ("numero do processo", "processo", "cnj"),
    FIELD_TRIBUNAL: ("tribunal", "vara", "orgao"),
    FIELD_TIPO_PROVIDENCIA: ("providencia", "tipo de acao", "acao necessaria"),
    FIELD_PRAZO: ("prazo",),
    FIELD_AUDIENCIA: ("audiencia",),
    FIELD_STATUS: ("status",),
    FIELD_RESUMO: ("resumo", "descricao", "observacao"),
    FIELD_LINK_CERTIDAO: ("certidao", "link intimacao", "link comunicacao", "djen"),
    FIELD_LINK_TRIBUNAL: ("link tribunal", "documento tribunal", "processo no tribunal"),
}

PROVIDENCIA_STATUS_LABELS: dict[str, str] = {
    "audiencia": "Audiência agendada",
    "manifestacao": "Manifestação pendente",
    "recurso": "Recurso pendente",
    "pagamento_deposito": "Pagamento/depósito pendente",
    "ciencia": "Apenas ciência",
    "indefinida": "Revisar manualmente",
}


def _normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


def resolve_field_for_column(title: str) -> str | None:
    """Associa uma coluna do board de litígio a um campo do domínio pelo título."""
    normalized = _normalize_title(title)
    for field, keywords in FIELD_TITLE_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return field
    return None


def find_column_by_field(columns: list[MondayColumn], field: str) -> MondayColumn | None:
    for column in columns:
        if resolve_field_for_column(column.title) == field:
            return column
    return None


def find_processo_column(columns: list[MondayColumn]) -> MondayColumn | None:
    return find_column_by_field(columns, FIELD_NUMERO_PROCESSO)


def _format_value(column: MondayColumn, field: str, raw_value: Any) -> Any:
    if field in (FIELD_PRAZO, FIELD_AUDIENCIA) and raw_value is not None:
        return {"date": raw_value.isoformat()}

    if field in (FIELD_STATUS, FIELD_TIPO_PROVIDENCIA) and column.column_type in {
        "status",
        "color",
    }:
        return {"label": str(raw_value)}

    if field in (FIELD_LINK_CERTIDAO, FIELD_LINK_TRIBUNAL) and column.column_type == "link":
        text = "Certidão DJEN" if field == FIELD_LINK_CERTIDAO else "Documento no tribunal"
        return format_link_column_value(url=str(raw_value), text=text)

    return str(raw_value)


def build_column_values(
    columns: list[MondayColumn],
    evento: EventoProcesso,
) -> dict[str, Any]:
    """Monta valores de colunas do Monday a partir de um `EventoProcesso`."""
    values: dict[str, Any] = {
        FIELD_NUMERO_PROCESSO: evento.numero_processo_formatado,
        FIELD_TRIBUNAL: evento.tribunal,
        FIELD_TIPO_PROVIDENCIA: PROVIDENCIA_STATUS_LABELS.get(
            evento.tipo_providencia.value,
            evento.tipo_providencia.value,
        ),
        FIELD_PRAZO: evento.prazo_data,
        FIELD_AUDIENCIA: evento.data_audiencia,
        FIELD_STATUS: "Requer atenção" if evento.requer_atencao else "Apenas ciência",
        FIELD_RESUMO: evento.descricao,
        FIELD_LINK_CERTIDAO: evento.certidao_url,
        FIELD_LINK_TRIBUNAL: evento.link_tribunal,
    }

    column_values: dict[str, Any] = {}
    for column in columns:
        field = resolve_field_for_column(column.title)
        if field is None:
            continue
        raw_value = values.get(field)
        if raw_value in (None, ""):
            continue
        column_values[column.id] = _format_value(column, field, raw_value)

    return column_values
