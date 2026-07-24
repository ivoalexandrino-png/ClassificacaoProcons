"""Parser de e-mails encaminhados da ALERJ (Comissão de Defesa do Consumidor)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Final

from bs4 import BeautifulSoup

from classificacao_procons.email.parser import normalize_email_address

ALERJ_ORIGINAL_SENDER: Final = "fferreira@alerj.rj.gov.br"
ALERJ_CC_SENDER: Final = "defesadoconsumidor@alerj.rj.gov.br"
ALERJ_DOMAIN: Final = "alerj.rj.gov.br"
ALERJ_STATE_LABEL: Final = "RJ"

_PROCEDURE_PATTERN = re.compile(
    r"procedimento\s+n[uú]mero\s*[^\d]*(\d+)\s*[\*/\s]*(\d{4})",
    re.IGNORECASE,
)
_PROCEDURE_SUBJECT_PATTERN = re.compile(
    r"reclama[cç][aã]o\s+de\s+n[.\sº°o]*\s*(\d+)\s*/\s*(\d{4})",
    re.IGNORECASE,
)
_NOTIFICATION_SUBJECT_PATTERN = re.compile(
    r"notifica[cç][aã]o\s+n[.\sº°o]*\s*(\d+)\s*/\s*(\d{4})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedAlerjEmail:
    protocol_number: str
    notification_number: str | None = None


class AlerjEmailParseError(ValueError):
    """E-mail ALERJ reconhecido, mas sem dados extraíveis."""


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return unescape(soup.get_text(separator="\n"))


def _format_protocol(number: str, year: str) -> str:
    return f"{number}/{year}"


def extract_alerj_protocol_number(text: str) -> str | None:
    match = _PROCEDURE_PATTERN.search(text)
    if match:
        return _format_protocol(match.group(1), match.group(2))

    match = _PROCEDURE_SUBJECT_PATTERN.search(text)
    if match:
        return _format_protocol(match.group(1), match.group(2))

    return None


def extract_alerj_notification_number(text: str) -> str | None:
    match = _NOTIFICATION_SUBJECT_PATTERN.search(text)
    if match:
        return _format_protocol(match.group(1), match.group(2))
    return None


def _body_mentions_alerj(body: str) -> bool:
    normalized = body.casefold()
    return (
        ALERJ_DOMAIN.casefold() in normalized
        or ALERJ_ORIGINAL_SENDER.casefold() in normalized
        or ALERJ_CC_SENDER.casefold() in normalized
    )


def is_alerj_notification(*, subject: str, sender: str, body: str = "") -> bool:
    combined = f"{subject}\n{body}"
    has_notification_subject = _NOTIFICATION_SUBJECT_PATTERN.search(subject) is not None
    has_procedure = extract_alerj_protocol_number(combined) is not None

    normalized_sender = normalize_email_address(sender)
    if normalized_sender.endswith(f"@{ALERJ_DOMAIN}"):
        return has_notification_subject or has_procedure

    if _body_mentions_alerj(body) and (has_notification_subject or has_procedure):
        return True

    return False


def parse_alerj_notification(
    *,
    subject: str,
    html: str | None = None,
    text: str | None = None,
) -> ParsedAlerjEmail:
    normalized_text = text or ""
    if html:
        normalized_text = f"{normalized_text}\n{_html_to_text(html)}".strip()

    combined = f"{subject}\n{normalized_text}"
    protocol_number = extract_alerj_protocol_number(combined)
    if not protocol_number:
        raise AlerjEmailParseError("Número do procedimento ALERJ não encontrado no e-mail.")

    return ParsedAlerjEmail(
        protocol_number=protocol_number,
        notification_number=extract_alerj_notification_number(subject),
    )
