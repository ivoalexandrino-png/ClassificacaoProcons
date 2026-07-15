"""Mapeamento de colunas do Monday por título."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any

FIELD_CONSUMER_NAME = "consumer_name"
FIELD_STATE = "state"
FIELD_PDF_URL = "pdf_url"
FIELD_PROTOCOL = "protocol_number"
FIELD_CPF = "consumer_cpf"
FIELD_COMPLAINT_DATE = "complaint_date"
FIELD_SAC_DEADLINE = "sac_deadline"
FIELD_LEGAL_DEADLINE = "legal_deadline"
FIELD_CAUSE = "cause"
FIELD_DOCS_SAC = "docs_sac"
FIELD_STATUS = "status"
FIELD_RESPONSE_DATE = "response_date"

FIELD_TITLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    FIELD_CONSUMER_NAME: ("nome", "consumidor", "cliente", "reclamante"),
    FIELD_STATE: ("estado", "uf", "state"),
    FIELD_PDF_URL: ("pdf", "drive", "link", "arquivo", "documento"),
    FIELD_PROTOCOL: ("cip", "fa", "protocolo", "numero"),
    FIELD_CPF: ("cpf",),
    FIELD_COMPLAINT_DATE: ("data reclamacao", "data da reclamacao", "data reclama", "abertura"),
    FIELD_SAC_DEADLINE: ("prazo sac",),
    FIELD_LEGAL_DEADLINE: ("prazo juridico", "prazo legal"),
    FIELD_CAUSE: ("causa", "motivo", "classificacao", "assunto"),
    FIELD_DOCS_SAC: ("docs sac",),
    FIELD_STATUS: ("status",),
    FIELD_RESPONSE_DATE: ("data da resposta legal", "resposta legal/baixa"),
}


@dataclass(frozen=True)
class MondayColumn:
    id: str
    title: str
    column_type: str


def _normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


def resolve_field_for_column(title: str) -> str | None:
    """Associa uma coluna do board a um campo do domínio pelo título."""
    normalized = _normalize_title(title)
    for field, keywords in FIELD_TITLE_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return field
    return None


def build_column_values(
    columns: list[MondayColumn],
    *,
    consumer_name: str,
    state: str,
    pdf_url: str | None,
    protocol_number: str,
    consumer_cpf: str,
    complaint_date: date | None,
    sac_deadline: date | None,
    legal_deadline: date | None,
    cause: str,
) -> dict[str, Any]:
    """Monta valores de colunas para create_item."""
    values: dict[str, str | date | None] = {
        FIELD_CONSUMER_NAME: consumer_name,
        FIELD_STATE: state,
        FIELD_PDF_URL: pdf_url,
        FIELD_PROTOCOL: protocol_number,
        FIELD_CPF: consumer_cpf,
        FIELD_COMPLAINT_DATE: complaint_date,
        FIELD_SAC_DEADLINE: sac_deadline,
        FIELD_LEGAL_DEADLINE: legal_deadline,
        FIELD_CAUSE: cause,
    }

    column_values: dict[str, Any] = {}
    for column in columns:
        field = resolve_field_for_column(column.title)
        if field is None or field == FIELD_CONSUMER_NAME:
            continue

        raw_value = values.get(field)
        if raw_value in (None, ""):
            continue

        column_values[column.id] = _format_column_value(column.column_type, raw_value)

    return column_values


def find_protocol_column(columns: list[MondayColumn]) -> MondayColumn | None:
    for column in columns:
        if resolve_field_for_column(column.title) == FIELD_PROTOCOL:
            return column
    return None


def find_column_by_field(columns: list[MondayColumn], field: str) -> MondayColumn | None:
    for column in columns:
        if resolve_field_for_column(column.title) == field:
            return column
    return None


def parse_link_column_value(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return raw_value.strip() or None
    if isinstance(payload, dict):
        url = str(payload.get("url", "")).strip()
        return url or None
    return None


def parse_status_text(text: str | None) -> str | None:
    if not text:
        return None
    return text.strip()


def _format_column_value(column_type: str, value: str | date) -> Any:
    if isinstance(value, date):
        return {"date": value.isoformat()}

    if column_type == "link":
        return {"url": value, "text": "PDF Procon"}

    if column_type in {"status", "color"}:
        return {"label": value}

    return str(value)
