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
FIELD_RESPONSE_FULL = "response_full_url"
FIELD_RESPONSE_SUMMARY = "response_summary_url"
FIELD_RESPONSE_UNIFIED_PDF = "response_unified_pdf_url"

FIELD_TITLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    FIELD_CONSUMER_NAME: ("nome", "consumidor", "cliente", "reclamante"),
    FIELD_STATE: ("estado", "uf", "state"),
    FIELD_RESPONSE_FULL: ("resposta completa",),
    FIELD_RESPONSE_SUMMARY: ("resumo resposta", "resumo portal", "resposta resumo"),
    FIELD_RESPONSE_UNIFIED_PDF: ("pdf unificado", "resposta unificada", "documentos unificados"),
    FIELD_PDF_URL: ("pdf procon", "link pdf", "pdf drive"),
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

        column_values[column.id] = format_column_value(column.column_type, raw_value)

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


def format_link_column_value(*, url: str, text: str) -> dict[str, str]:
    return {"url": url, "text": text}


def build_response_column_values(
    columns: list[MondayColumn],
    *,
    full_response_url: str,
    summary_response_url: str,
    unified_pdf_url: str | None = None,
) -> dict[str, Any]:
    """Monta valores de colunas link para respostas elaboradas."""
    values: dict[str, str | None] = {
        FIELD_RESPONSE_FULL: full_response_url,
        FIELD_RESPONSE_SUMMARY: summary_response_url,
        FIELD_RESPONSE_UNIFIED_PDF: unified_pdf_url,
    }
    link_labels = {
        FIELD_RESPONSE_FULL: "Resposta completa",
        FIELD_RESPONSE_SUMMARY: "Resumo portal",
        FIELD_RESPONSE_UNIFIED_PDF: "PDF unificado",
    }

    column_values: dict[str, Any] = {}
    for column in columns:
        field = resolve_field_for_column(column.title)
        if field is None or column.column_type != "link":
            continue
        raw_value = values.get(field)
        if not raw_value:
            continue
        column_values[column.id] = format_link_column_value(
            url=str(raw_value),
            text=link_labels.get(field, "Documento"),
        )
    return column_values


def format_column_value(
    column_type: str,
    value: str | date,
    *,
    link_text: str = "PDF Procon",
) -> Any:
    if isinstance(value, date):
        return {"date": value.isoformat()}

    if column_type == "link":
        return format_link_column_value(url=str(value), text=link_text)

    if column_type in {"status", "color"}:
        return {"label": str(value)}

    if column_type == "long_text":
        return {"text": str(value)}

    return str(value)
