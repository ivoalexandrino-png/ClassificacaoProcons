"""Extrai dados da notificação anexa em PDF da ALERJ."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from pypdf import PdfReader

from classificacao_procons.alerj.email_parser import ALERJ_STATE_LABEL
from classificacao_procons.models import ProconComplaint

_PROTOCOL_PATTERN = re.compile(
    r"reclama[cç][aã]o\s+de\s+n[.\sº°o]*\s*(\d+)\s*/\s*(\d{4})",
    re.IGNORECASE,
)
_CONSUMER_PATTERN = re.compile(
    r"da\s+sra\.?\s+(.+?),\s*residente",
    re.IGNORECASE | re.DOTALL,
)
_CPF_PATTERN = re.compile(
    r"cpf\s*:\s*([\d.\-]+)",
    re.IGNORECASE,
)
_CAUSE_PATTERN = re.compile(
    r"cpf\s*:\s*[\d.\-]+\s*\n+(.*?)(?:\n\s*reclama[cç][aã]o\s+com\s+base|\n\s*e-mail\s*:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_DOCUMENT_DATE_PATTERN = re.compile(
    r"rio\s+de\s+janeiro,\s*(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})",
    re.IGNORECASE,
)
_HEADER_LINE_PATTERNS = (
    re.compile(r"^notifica[cç][aã]o", re.IGNORECASE),
    re.compile(r"^assembleia legislativa", re.IGNORECASE),
    re.compile(r"^notificado:", re.IGNORECASE),
)

_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def _clean_cause(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(pattern.search(stripped) for pattern in _HEADER_LINE_PATTERNS):
            continue
        lines.append(stripped)
    return " ".join(lines)


class AlerjPdfParseError(ValueError):
    """PDF ALERJ reconhecido, mas sem dados extraíveis."""


@dataclass(frozen=True)
class ParsedAlerjPdf:
    protocol_number: str
    consumer_name: str
    consumer_cpf: str
    complaint_date: date | None
    cause: str


def _format_protocol(number: str, year: str) -> str:
    return f"{number}/{year}"


def _parse_brazilian_date(value: str) -> date | None:
    value = value.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_document_date(text: str) -> date | None:
    match = _DOCUMENT_DATE_PATTERN.search(text)
    if not match:
        return None
    day = int(match.group(1))
    month_name = match.group(2).casefold()
    year = int(match.group(3))
    month = _MONTHS.get(month_name)
    if month is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _normalize_cpf(value: str) -> str:
    return re.sub(r"\D", "", value)


def _extract_pdf_text(pdf_path: Path) -> str:
    if not pdf_path.exists():
        raise AlerjPdfParseError(f"PDF não encontrado: {pdf_path}")
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as exc:
        raise AlerjPdfParseError(f"Falha ao abrir PDF ALERJ: {pdf_path}") from exc
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    text = "\n".join(pages)
    if not text.strip():
        raise AlerjPdfParseError("PDF ALERJ sem texto extraível.")
    return text


def parse_alerj_pdf_text(text: str) -> ParsedAlerjPdf:
    protocol_match = _PROTOCOL_PATTERN.search(text)
    if not protocol_match:
        raise AlerjPdfParseError("Número da reclamação ALERJ não encontrado no PDF.")

    consumer_match = _CONSUMER_PATTERN.search(text)
    if not consumer_match:
        raise AlerjPdfParseError("Nome da consumidora não encontrado no PDF.")

    cpf_match = _CPF_PATTERN.search(text)
    if not cpf_match:
        raise AlerjPdfParseError("CPF da consumidora não encontrado no PDF.")

    cause = ""
    cause_match = _CAUSE_PATTERN.search(text)
    if cause_match:
        cause = _clean_cause(cause_match.group(1))

    consumer_name = " ".join(consumer_match.group(1).split()).strip()
    if not consumer_name:
        raise AlerjPdfParseError("Nome da consumidora vazio no PDF.")

    return ParsedAlerjPdf(
        protocol_number=_format_protocol(protocol_match.group(1), protocol_match.group(2)),
        consumer_name=consumer_name,
        consumer_cpf=_normalize_cpf(cpf_match.group(1)),
        complaint_date=_parse_document_date(text),
        cause=cause,
    )


def parse_alerj_pdf(pdf_path: str | Path) -> ProconComplaint:
    """Extrai reclamação do PDF anexo da ALERJ."""
    parsed = parse_alerj_pdf_text(_extract_pdf_text(Path(pdf_path)))
    return ProconComplaint(
        access_code=parsed.protocol_number,
        consumer_name=parsed.consumer_name,
        consumer_cpf=parsed.consumer_cpf,
        cip_fa_number=parsed.protocol_number,
        complaint_date=parsed.complaint_date,
        response_deadline=None,
        cause=parsed.cause,
        state=ALERJ_STATE_LABEL,
        pdf_path=str(pdf_path),
    )
