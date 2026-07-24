"""Parser de e-mails encaminhados do Procon SC (processo SSP)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Final

from bs4 import BeautifulSoup

from classificacao_procons.email.parser import normalize_email_address

SC_ORIGINAL_SENDER: Final = "protocolocartorio@procon.sc.gov.br"
SC_STATE_LABEL: Final = "SC"

_SSP_SUBJECT_PATTERN = re.compile(
    r"processo\s+ssp\s+(\d+/\d{4})",
    re.IGNORECASE,
)
_SSP_BODY_PATTERN = re.compile(
    r"processo\s+ssp\s+(\d+/\d{4})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedScSspEmail:
    protocol_number: str


class ScEmailParseError(ValueError):
    """E-mail SSP reconhecido, mas sem dados extraíveis."""


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return unescape(soup.get_text(separator="\n"))


def extract_ssp_protocol_number(text: str) -> str | None:
    match = _SSP_SUBJECT_PATTERN.search(text)
    if match:
        return match.group(1)
    return None


def is_sc_ssp_notification(*, subject: str, sender: str, body: str = "") -> bool:
    combined = f"{subject}\n{body}"
    if extract_ssp_protocol_number(combined) is None:
        return False

    normalized_sender = normalize_email_address(sender)
    if normalized_sender == SC_ORIGINAL_SENDER:
        return True

    normalized_body = body.casefold()
    if SC_ORIGINAL_SENDER.casefold() in normalized_body:
        return True

    if _SSP_BODY_PATTERN.search(subject):
        return True

    return False


def parse_sc_ssp_notification(
    *,
    subject: str,
    html: str | None = None,
    text: str | None = None,
) -> ParsedScSspEmail:
    normalized_text = text or ""
    if html:
        normalized_text = f"{normalized_text}\n{_html_to_text(html)}".strip()

    protocol_number = extract_ssp_protocol_number(f"{subject}\n{normalized_text}")
    if not protocol_number:
        raise ScEmailParseError("Número do processo SSP não encontrado no e-mail.")

    return ParsedScSspEmail(protocol_number=protocol_number)
