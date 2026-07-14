"""Identificação e extração de e-mails de notificação CIP do Procon-SP."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Final

from bs4 import BeautifulSoup

PROCON_SP_SENDER: Final = "procon.naoresponder@procon.sp.gov.br"
PROCON_SP_SUBJECT: Final = "Fundação Procon-SP - Notificação de emissão de CIP"
PROCON_PORTAL_HOST: Final = "fornecedor2.procon.sp.gov.br"
PROCON_PORTAL_LOGIN_URL: Final = f"https://{PROCON_PORTAL_HOST}/login"

_URL_PATTERN = re.compile(
    rf"https?://{re.escape(PROCON_PORTAL_HOST)}[^\s\"'<>]*",
    re.IGNORECASE,
)

_CODE_LABEL_PATTERN = re.compile(
    r"(?:c[oó]digo(?:\s+de\s+acesso)?|chave(?:\s+de\s+acesso)?)\s*[:\-]?\s*"
    r"([A-Za-z0-9][A-Za-z0-9\-]{3,})",
    re.IGNORECASE,
)

_STANDALONE_CODE_PATTERN = re.compile(
    r"\b([A-Z0-9]{6,}(?:-[A-Z0-9]+)*)\b",
)


@dataclass(frozen=True)
class ParsedEmailContent:
    portal_url: str
    access_code: str


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


def _is_likely_access_code(candidate: str) -> bool:
    if len(candidate) < 6:
        return False
    if candidate.lower() in {"procon", "brasil", "acesso", "codigo", "código"}:
        return False
    return any(char.isdigit() for char in candidate) or "-" in candidate


def _extract_access_code(text: str) -> str | None:
    label_match = _CODE_LABEL_PATTERN.search(text)
    if label_match:
        code = label_match.group(1).strip()
        if _is_likely_access_code(code):
            return code

    for match in _STANDALONE_CODE_PATTERN.finditer(text):
        candidate = match.group(1)
        if _is_likely_access_code(candidate):
            return candidate
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

    return ParsedEmailContent(portal_url=portal_url, access_code=access_code)
