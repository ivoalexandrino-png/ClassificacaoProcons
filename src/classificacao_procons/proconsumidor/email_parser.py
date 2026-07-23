"""Parser de e-mails de notificação do Proconsumidor."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Final

from bs4 import BeautifulSoup

from classificacao_procons.email.parser import normalize_email_address

PROCONSUMIDOR_SENDER: Final = "admin@proconsumidor.mj.gov.br"
PROCONSUMIDOR_SUBJECT: Final = "Proconsumidor - Notificação"
PROCONSUMIDOR_CARTA_SUBJECT: Final = "Notificação de Carta"
PROCONSUMIDOR_SUBJECTS: Final = (
    PROCONSUMIDOR_SUBJECT,
    PROCONSUMIDOR_CARTA_SUBJECT,
)
PROCONSUMIDOR_PORTAL_URL: Final = "https://proconsumidor.mj.gov.br/#/login"

_COMPLAINT_NUMBER_PATTERN = re.compile(
    r"reclama[cç][aã]o\s+([\d.\-]+)",
    re.IGNORECASE,
)
_REGIONAL_ORG_PATTERN = re.compile(
    r"reclama[cç][aã]o\s+[\d.\-]+\s+(?:do|pelo)\s+(.+?)(?:\.|$)",
    re.IGNORECASE | re.DOTALL,
)
_STATE_SUFFIX_PATTERN = re.compile(
    r"(?:^|[\s\-/])([A-Z]{2})\s*$",
)


@dataclass(frozen=True)
class ParsedProconsumidorEmail:
    complaint_number: str
    regional_org: str | None = None
    state: str | None = None


class ProconsumidorEmailParseError(ValueError):
    """E-mail Proconsumidor reconhecido, mas sem dados extraíveis."""


def is_proconsumidor_notification(*, subject: str, sender: str) -> bool:
    normalized_subject = " ".join(subject.split())
    normalized_sender = normalize_email_address(sender)
    if normalized_sender != PROCONSUMIDOR_SENDER:
        return False
    return normalized_subject in PROCONSUMIDOR_SUBJECTS


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return unescape(soup.get_text(separator="\n"))


def extract_proconsumidor_complaint_number(text: str) -> str | None:
    match = _COMPLAINT_NUMBER_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return None


def extract_proconsumidor_regional_org(text: str) -> str | None:
    match = _REGIONAL_ORG_PATTERN.search(text)
    if not match:
        return None
    org = " ".join(match.group(1).split()).strip()
    return org or None


def extract_proconsumidor_state(regional_org: str | None) -> str | None:
    if not regional_org:
        return None
    normalized = " ".join(regional_org.split())
    suffix_match = _STATE_SUFFIX_PATTERN.search(normalized)
    if suffix_match:
        return suffix_match.group(1).upper()
    if " - " in normalized:
        candidate = normalized.rsplit(" - ", 1)[-1].strip().upper()
        if len(candidate) == 2 and candidate.isalpha():
            return candidate
    return None


def parse_proconsumidor_notification_body(
    *,
    html: str | None = None,
    text: str | None = None,
) -> ParsedProconsumidorEmail:
    if not html and not text:
        raise ProconsumidorEmailParseError("Corpo do e-mail vazio.")

    normalized_text = text or ""
    if html:
        normalized_text = f"{normalized_text}\n{_html_to_text(html)}".strip()

    complaint_number = extract_proconsumidor_complaint_number(normalized_text)
    if not complaint_number:
        raise ProconsumidorEmailParseError("Número da reclamação não encontrado no e-mail.")

    regional_org = extract_proconsumidor_regional_org(normalized_text)
    return ParsedProconsumidorEmail(
        complaint_number=complaint_number,
        regional_org=regional_org,
        state=extract_proconsumidor_state(regional_org),
    )
