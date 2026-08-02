"""Identidade dos signatários internos B4A no Autentique.

Regras Jan vs Luciano (nomes e e-mails): ver `AGENTS.md` e `tests/test_signer_identity.py`.
"""

from __future__ import annotations

import re
import unicodedata

from classificacao_procons.contratos.autentique.client import AutentiqueSigner
from classificacao_procons.contratos.constants import (
    SIGNER_DISPLAY_NAME_JAN,
    SIGNER_DISPLAY_NAME_LUCIANO,
    SIGNER_EMAIL_JAN,
    SIGNER_EMAIL_LUCIANO,
)


def normalize_signer_display_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    collapsed = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", collapsed).strip()


_JAN_NAME_TOKENS = frozenset(
    {
        "jan",
        normalize_signer_display_name(SIGNER_DISPLAY_NAME_JAN),
    }
)
_LUCIANO_NAME_MARKERS = (
    normalize_signer_display_name(SIGNER_DISPLAY_NAME_LUCIANO),
    "luciano",
    "beauty for all",
)


def _normalize_email(value: str) -> str:
    return value.casefold().strip()


def _email_local_and_domain(email: str) -> tuple[str, str]:
    local, _, domain = _normalize_email(email).partition("@")
    return local, domain


def email_matches_jan(email: str) -> bool:
    normalized = _normalize_email(email)
    if normalized == _normalize_email(SIGNER_EMAIL_JAN):
        return True
    local, domain = _email_local_and_domain(email)
    if not domain or "b4a" not in domain:
        return False
    return local == "assinador" or local.startswith("assinador")


def email_matches_luciano(email: str) -> bool:
    normalized = _normalize_email(email)
    if normalized == _normalize_email(SIGNER_EMAIL_LUCIANO):
        return True
    if normalized.startswith("juridico@b4a"):
        return True
    local, domain = _email_local_and_domain(email)
    if not domain or "b4a" not in domain:
        return False
    return local == "juridico" or local.startswith("juridico")


def name_matches_jan(name: str) -> bool:
    normalized = normalize_signer_display_name(name)
    if not normalized:
        return False
    if normalized in _JAN_NAME_TOKENS:
        return True
    tokens = normalized.split()
    if any(token in _JAN_NAME_TOKENS for token in tokens):
        return True
    return bool(re.search(r"\bjan\b", normalized))


def name_matches_luciano(name: str) -> bool:
    normalized = normalize_signer_display_name(name)
    if not normalized:
        return False
    if normalized == "luciano" or "luciano" in normalized.split():
        return True
    return any(marker in normalized for marker in _LUCIANO_NAME_MARKERS)


def signer_is_jan(signer: AutentiqueSigner) -> bool:
    if signer.email and email_matches_jan(signer.email):
        return True
    if signer.name and name_matches_jan(signer.name):
        return True
    return False


def signer_is_luciano(signer: AutentiqueSigner) -> bool:
    if signer_is_jan(signer):
        return False
    if signer.email and email_matches_luciano(signer.email):
        return True
    if signer.name and name_matches_luciano(signer.name):
        return True
    return False


def find_jan_signer(signatures: tuple[AutentiqueSigner, ...]) -> AutentiqueSigner | None:
    for signer in signatures:
        if signer_is_jan(signer):
            return signer
    return None


def find_luciano_signer(signatures: tuple[AutentiqueSigner, ...]) -> AutentiqueSigner | None:
    for signer in signatures:
        if signer_is_luciano(signer):
            return signer
    return None
