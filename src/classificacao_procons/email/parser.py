"""Identificação e extração de e-mails de notificação CIP do Procon-SP."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Final

from bs4 import BeautifulSoup

PROCON_SP_SENDER: Final = "procon.naoresponder@procon.sp.gov.br"
PROCON_SP_SUBJECT: Final = "Fundação Procon-SP - Notificação de emissão de CIP"
PROCON_PA_SUBJECT_PREFIX: Final = "Processo Administrativo Aberto:"
PROCON_PORTAL_HOST: Final = "fornecedor2.procon.sp.gov.br"
PROCON_PORTAL_LOGIN_URL: Final = f"https://{PROCON_PORTAL_HOST}/login"

_URL_PATTERN = re.compile(
    rf"https?://{re.escape(PROCON_PORTAL_HOST)}[^\s\"'<>]*",
    re.IGNORECASE,
)

_CODE_LABEL_PATTERN = re.compile(
    r"c[oó]digo(?:\s+de\s+acesso)?\s*:\s*([^\s<]+)",
    re.IGNORECASE,
)

_PROTOCOL_PATTERN = re.compile(
    r"protocolo\s+(\d+/\d+)",
    re.IGNORECASE,
)

_DEADLINE_PATTERN = re.compile(
    r"prazo final para an[aá]lise e resposta [eé]\s*(\d{2}-\d{2}-\d{4})",
    re.IGNORECASE,
)

_PA_NUMBER_PATTERN = re.compile(
    r"processo\s+administrativo\s+aberto\s*:\s*([\d.]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedEmailContent:
    portal_url: str
    access_code: str
    protocol_number: str | None = None
    response_deadline: str | None = None


class ProconEmailParseError(ValueError):
    """E-mail reconhecido como notificação Procon, mas sem dados extraíveis."""


def normalize_email_address(value: str) -> str:
    """Extrai o endereço de e-mail de um campo From (ex.: 'Nome <email@dominio>')."""
    match = re.search(r"<([^>]+)>", value)
    if match:
        return match.group(1).strip().lower()
    return value.strip().lower()


def is_procon_cip_notification(*, subject: str, sender: str) -> bool:
    """Retorna True se o e-mail corresponde a uma notificação de CIP do Procon-SP."""
    normalized_subject = " ".join(subject.split())
    normalized_sender = normalize_email_address(sender)
    return (
        normalized_subject == PROCON_SP_SUBJECT
        and normalized_sender == PROCON_SP_SENDER
    )


def is_procon_pa_notification(*, subject: str, sender: str) -> bool:
    """Retorna True se o e-mail corresponde a abertura de Processo Administrativo."""
    normalized_subject = " ".join(subject.split())
    normalized_sender = normalize_email_address(sender)
    if normalized_sender != PROCON_SP_SENDER:
        return False
    return normalized_subject.lower().startswith(PROCON_PA_SUBJECT_PREFIX.lower())


def is_procon_notification(*, subject: str, sender: str) -> bool:
    """Retorna True para notificações CIP ou Processo Administrativo do Procon-SP."""
    return is_procon_cip_notification(subject=subject, sender=sender) or is_procon_pa_notification(
        subject=subject,
        sender=sender,
    )


def extract_administrative_process_number(subject: str) -> str | None:
    """Extrai o número do processo administrativo do assunto do e-mail."""
    normalized_subject = " ".join(subject.split())
    match = _PA_NUMBER_PATTERN.search(normalized_subject)
    if match:
        return match.group(1).strip()
    return None


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    return unescape(text)


def _extract_portal_url(*, html: str | None, text: str) -> str | None:
    if html:
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if PROCON_PORTAL_HOST in href.lower():
                return href

    for match in _URL_PATTERN.finditer(text):
        return match.group(0).rstrip(".,;)")
    return None


def _extract_access_code(text: str) -> str | None:
    label_match = _CODE_LABEL_PATTERN.search(text)
    if label_match:
        return label_match.group(1).strip()
    return None


def _extract_protocol_number(text: str) -> str | None:
    match = _PROTOCOL_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return None


def _extract_response_deadline(text: str) -> str | None:
    match = _DEADLINE_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return None


def parse_procon_notification_body(
    *,
    html: str | None = None,
    text: str | None = None,
) -> ParsedEmailContent:
    """
    Extrai URL do portal e código de acesso do corpo do e-mail.

    Pelo menos um de `html` ou `text` deve ser informado.
    """
    if not html and not text:
        raise ProconEmailParseError("Corpo do e-mail vazio.")

    normalized_text = text or ""
    if html:
        html_text = _html_to_text(html)
        normalized_text = f"{normalized_text}\n{html_text}".strip()

    portal_url = _extract_portal_url(html=html, text=normalized_text)
    if not portal_url:
        portal_url = PROCON_PORTAL_LOGIN_URL

    access_code = _extract_access_code(normalized_text)
    if not access_code:
        raise ProconEmailParseError("Código de acesso não encontrado no corpo do e-mail.")

    return ParsedEmailContent(
        portal_url=portal_url,
        access_code=access_code,
        protocol_number=_extract_protocol_number(normalized_text),
        response_deadline=_extract_response_deadline(normalized_text),
    )
