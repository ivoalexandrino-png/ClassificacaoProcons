"""Parser de e-mails do Fale Procon Uberlândia."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from typing import Final

from bs4 import BeautifulSoup

from classificacao_procons.email.parser import normalize_email_address

UBERLANDIA_SENDER: Final = "faleprocon@uberlandia.mg.gov.br"
UBERLANDIA_STATE_LABEL: Final = "MG"
UBERLANDIA_PORTAL_URL: Final = "https://faleprocon.uberlandia.mg.gov.br/empresas"

_PROCESS_PATTERN = re.compile(
    r"(?:acompanhe o processo|processo)\s+([\d.]+)",
    re.IGNORECASE,
)
_NOTIFICATION_DATE_PATTERN = re.compile(
    r"1ª\s+notifica[cç][aã]o\s+eletr[oô]nica\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_CONSUMER_PATTERN = re.compile(
    r"nome\s+e\s+documento:\s*(.+?)\s*\|\s*([\d.\-/]+)",
    re.IGNORECASE,
)
_DESCRIPTION_PATTERN = re.compile(
    r"descri[cç][aã]o\s*(.*?)\s*solu[cç][aã]o",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class ParsedUberlandiaEmail:
    protocol_number: str
    consumer_name: str
    consumer_cpf: str
    complaint_date: date | None = None
    cause: str | None = None


class UberlandiaEmailParseError(ValueError):
    """E-mail Uberlândia reconhecido, mas sem dados extraíveis."""


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
    return value.strip().strip(".")


def extract_uberlandia_protocol_number(text: str) -> str | None:
    match = _PROCESS_PATTERN.search(text)
    if not match:
        return None
    return _normalize_protocol_number(match.group(1))


def is_uberlandia_notification(*, subject: str, sender: str, body: str = "") -> bool:
    normalized_sender = normalize_email_address(sender)
    if normalized_sender != UBERLANDIA_SENDER:
        return False
    combined = f"{subject}\n{body}"
    if extract_uberlandia_protocol_number(combined) is None:
        return False
    return "nome e documento:" in combined.casefold()


def parse_uberlandia_notification_body(
    *,
    html: str | None = None,
    text: str | None = None,
) -> ParsedUberlandiaEmail:
    if not html and not text:
        raise UberlandiaEmailParseError("Corpo do e-mail vazio.")

    normalized_text = text or ""
    if html:
        normalized_text = f"{normalized_text}\n{_html_to_text(html)}".strip()

    protocol_number = extract_uberlandia_protocol_number(normalized_text)
    if not protocol_number:
        raise UberlandiaEmailParseError("Número do processo não encontrado no e-mail.")

    consumer_match = _CONSUMER_PATTERN.search(normalized_text)
    if not consumer_match:
        raise UberlandiaEmailParseError("Dados da consumidora não encontrados no e-mail.")

    consumer_name = " ".join(consumer_match.group(1).split()).strip()
    consumer_cpf = _normalize_cpf(consumer_match.group(2))
    if not consumer_name:
        raise UberlandiaEmailParseError("Nome da consumidora vazio no e-mail.")

    complaint_date = None
    date_match = _NOTIFICATION_DATE_PATTERN.search(normalized_text)
    if date_match:
        complaint_date = _parse_brazilian_date(date_match.group(1))

    cause = None
    description_match = _DESCRIPTION_PATTERN.search(normalized_text)
    if description_match:
        cause = " ".join(description_match.group(1).split()).strip()

    return ParsedUberlandiaEmail(
        protocol_number=protocol_number,
        consumer_name=consumer_name,
        consumer_cpf=consumer_cpf,
        complaint_date=complaint_date,
        cause=cause,
    )
