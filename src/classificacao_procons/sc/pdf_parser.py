"""Extrai dados da CIP anexa em PDF do Procon SC."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from pypdf import PdfReader

from classificacao_procons.models import ProconComplaint
from classificacao_procons.sc.email_parser import SC_STATE_LABEL

_PROTOCOL_PATTERN = re.compile(r"processo\s+ssp\s+(\d+/\d{4})", re.IGNORECASE)
_AUTUADO_PATTERN = re.compile(
    r"autuado\s+em:\s*(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_CPF_BLOCK_PATTERN = re.compile(
    r"cpf\s*\n\s*(\d{11})\s*\n\s*nome\s+completo\s*\n\s*([^\n]+)",
    re.IGNORECASE,
)
_RELATO_PATTERN = re.compile(
    r"relato\s+da\s+ocorr[eê]ncia\s*\n+(.*?)(?:\n\s*pedido\s+para\s+a\s+empresa|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_HEADER_LINE_PATTERNS = (
    re.compile(r"^\d+$"),
    re.compile(r"governo do estado", re.IGNORECASE),
    re.compile(r"enviar reclama", re.IGNORECASE),
)


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


class ScPdfParseError(ValueError):
    """PDF SSP reconhecido, mas sem dados extraíveis."""


@dataclass(frozen=True)
class ParsedScSspPdf:
    protocol_number: str
    consumer_name: str
    consumer_cpf: str
    complaint_date: date | None
    cause: str


def _parse_brazilian_date(value: str) -> date | None:
    value = value.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_cpf(value: str) -> str:
    return re.sub(r"\D", "", value)


def _extract_pdf_text(pdf_path: Path) -> str:
    if not pdf_path.exists():
        raise ScPdfParseError(f"PDF não encontrado: {pdf_path}")
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as exc:
        raise ScPdfParseError(f"Falha ao abrir PDF SSP: {pdf_path}") from exc
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    text = "\n".join(pages)
    if not text.strip():
        raise ScPdfParseError("PDF SSP sem texto extraível.")
    return text


def parse_sc_ssp_pdf_text(text: str) -> ParsedScSspPdf:
    protocol_match = _PROTOCOL_PATTERN.search(text)
    if not protocol_match:
        raise ScPdfParseError("Número do processo SSP não encontrado no PDF.")

    cpf_match = _CPF_BLOCK_PATTERN.search(text)
    if not cpf_match:
        raise ScPdfParseError("CPF e nome da consumidora não encontrados no PDF.")

    complaint_date = None
    autuado_match = _AUTUADO_PATTERN.search(text)
    if autuado_match:
        complaint_date = _parse_brazilian_date(autuado_match.group(1))

    cause = ""
    relato_match = _RELATO_PATTERN.search(text)
    if relato_match:
        cause = _clean_cause(relato_match.group(1))

    consumer_name = " ".join(cpf_match.group(2).split()).strip()
    if not consumer_name:
        raise ScPdfParseError("Nome da consumidora vazio no PDF.")

    return ParsedScSspPdf(
        protocol_number=protocol_match.group(1),
        consumer_name=consumer_name,
        consumer_cpf=_normalize_cpf(cpf_match.group(1)),
        complaint_date=complaint_date,
        cause=cause,
    )


def parse_sc_ssp_pdf(pdf_path: str | Path) -> ProconComplaint:
    """Extrai reclamação do PDF anexo do Procon SC."""
    parsed = parse_sc_ssp_pdf_text(_extract_pdf_text(Path(pdf_path)))
    return ProconComplaint(
        access_code=parsed.protocol_number,
        consumer_name=parsed.consumer_name,
        consumer_cpf=parsed.consumer_cpf,
        cip_fa_number=parsed.protocol_number,
        complaint_date=parsed.complaint_date,
        response_deadline=None,
        cause=parsed.cause,
        state=SC_STATE_LABEL,
        pdf_path=str(pdf_path),
    )
