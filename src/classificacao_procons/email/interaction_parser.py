"""E-mails de interação do consumidor (Procon-SP)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from classificacao_procons.email.parser import (
    PROCON_PORTAL_LOGIN_URL,
    ProconEmailParseError,
    _extract_access_code,
    _extract_portal_url,
    _extract_protocol_number,
    _html_to_text,
    is_procon_naoresponder_sender,
    normalize_email_address,
)

PROCON_INTERACTION_SUBJECT_FRAGMENT: Final = "interação do consumidor"


@dataclass(frozen=True)
class ParsedConsumerInteractionEmail:
    portal_url: str
    access_code: str | None
    protocol_number: str


def is_procon_consumer_interaction(*, subject: str, sender: str) -> bool:
    """Retorna True para notificação de interação do consumidor no Procon-SP."""
    if not is_procon_naoresponder_sender(sender):
        return False
    normalized_subject = " ".join(subject.split()).lower()
    return PROCON_INTERACTION_SUBJECT_FRAGMENT in normalized_subject


def parse_procon_consumer_interaction_body(
    *,
    html: str | None = None,
    text: str | None = None,
) -> ParsedConsumerInteractionEmail:
    """Extrai protocolo e, quando presente, código de acesso do corpo do e-mail."""
    if not html and not text:
        raise ProconEmailParseError("Corpo do e-mail vazio.")

    normalized_text = text or ""
    if html:
        normalized_text = f"{normalized_text}\n{_html_to_text(html)}".strip()

    protocol_number = _extract_protocol_number(normalized_text)
    if not protocol_number:
        protocol_match = re.search(
            r"reclama[çc][aã]o\s+(\d+/\d+)",
            normalized_text,
            re.IGNORECASE,
        )
        if protocol_match:
            protocol_number = protocol_match.group(1).strip()

    if not protocol_number:
        raise ProconEmailParseError("Protocolo não encontrado no corpo do e-mail.")

    portal_url = _extract_portal_url(html=html, text=normalized_text) or PROCON_PORTAL_LOGIN_URL
    access_code = _extract_access_code(normalized_text)

    return ParsedConsumerInteractionEmail(
        portal_url=portal_url,
        access_code=access_code,
        protocol_number=protocol_number,
    )


def normalize_procon_sender(sender: str) -> str:
    """Expõe normalização de remetente para testes e Gmail."""
    return normalize_email_address(sender)
