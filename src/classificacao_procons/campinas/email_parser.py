"""Parser de e-mails de CIP do Procon Campinas."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from typing import Final

from bs4 import BeautifulSoup

from classificacao_procons.email.parser import normalize_email_address

CAMPINAS_SENDER: Final = "procon.adm@campinas.sp.gov.br"
CAMPINAS_STATE_LABEL: Final = "Campinas"
CAMPINAS_PORTAL_URL: Final = "https://procon.campinas.sp.gov.br/"

_CIP_NUMBER_PATTERN = re.compile(
    r"cip\s*n[º°o.]?\s*[-:]?\s*([\d/]+)(?:/cip)?",
    re.IGNORECASE,
)
_CPF_PATTERN = re.compile(r"cpf\s*[:\-]?\s*([\d.\-/]+)", re.IGNORECASE)
_NAME_PATTERN = re.compile(
    r"nome\s*[:\-]?\s*([^\n<]+)",
    re.IGNORECASE,
)
_DATE_PATTERN = re.compile(
    r"data\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedCampinasEmail:
    protocol_number: str
    consumer_name: str | None = None
    consumer_cpf: str | None = None
    complaint_date: date | None = None


class CampinasEmailParseError(ValueError):
    """E-mail Campinas reconhecido, mas sem dados extraíveis."""


def is_campinas_notification(*, subject: str, sender: str) -> bool:
    normalized_sender = normalize_email_address(sender)
    if normalized_sender != CAMPINAS_SENDER:
        return False
    normalized_subject = " ".join(subject.split()).casefold()
    return "cip" in normalized_subject or normalized_subject == "notificação"


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return unescape(soup.get_text(separator="\n"))


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


def _normalize_protocol_number(value: str) -> str:
    cleaned = value.strip().replace("/CIP", "").replace("/cip", "")
    return cleaned.rstrip("/")


def extract_campinas_protocol_number(text: str) -> str | None:
    match = _CIP_NUMBER_PATTERN.search(text)
    if not match:
        return None
    return _normalize_protocol_number(match.group(1))


def parse_campinas_notification_body(
    *,
    html: str | None = None,
    text: str | None = None,
) -> ParsedCampinasEmail:
    if not html and not text:
        raise CampinasEmailParseError("Corpo do e-mail vazio.")

    normalized_text = text or ""
    if html:
        normalized_text = f"{normalized_text}\n{_html_to_text(html)}".strip()

    protocol_number = extract_campinas_protocol_number(normalized_text)
    if not protocol_number:
        raise CampinasEmailParseError("Número da CIP não encontrado no e-mail.")

    consumer_name = None
    name_match = _NAME_PATTERN.search(normalized_text)
    if name_match:
        consumer_name = name_match.group(1).strip()
        if consumer_name.upper().startswith("CPF"):
            consumer_name = None

    consumer_cpf = None
    cpf_match = _CPF_PATTERN.search(normalized_text)
    if cpf_match:
        consumer_cpf = _normalize_cpf(cpf_match.group(1))

    complaint_date = None
    date_match = _DATE_PATTERN.search(normalized_text)
    if date_match:
        complaint_date = _parse_brazilian_date(date_match.group(1))

    return ParsedCampinasEmail(
        protocol_number=protocol_number,
        consumer_name=consumer_name,
        consumer_cpf=consumer_cpf,
        complaint_date=complaint_date,
    )
