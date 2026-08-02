"""Identidade dos signatários internos B4A no Autentique."""

from __future__ import annotations

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
    return "".join(char for char in normalized if not unicodedata.combining(char)).strip()


def signer_is_jan(signer: AutentiqueSigner) -> bool:
    if signer.email and signer.email.casefold().strip() == SIGNER_EMAIL_JAN.casefold():
        return True
    if signer.name:
        return normalize_signer_display_name(signer.name) == normalize_signer_display_name(
            SIGNER_DISPLAY_NAME_JAN,
        )
    return False


def signer_is_luciano(signer: AutentiqueSigner) -> bool:
    if signer.email and signer.email.casefold().strip() == SIGNER_EMAIL_LUCIANO.casefold():
        return True
    if signer.name:
        return normalize_signer_display_name(signer.name) == normalize_signer_display_name(
            SIGNER_DISPLAY_NAME_LUCIANO,
        )
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
