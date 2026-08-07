"""Exceções à pausa de criação no Controle (piloto controlado)."""

from __future__ import annotations

from classificacao_procons.contratos.controle_create_policy import is_controle_create_paused
from classificacao_procons.contratos.controle_dedup import normalize_controle_title

# Piloto: novo distrato após bloqueio do documento anterior (título no Autentique).
BRUNO_DISTRATO_V2_NORMALIZED = normalize_controle_title(
    "Distrato Bruno Santos de Castro - 25.06.2026 (2)",
)
BRUNO_DISTRATO_V1_NORMALIZED = normalize_controle_title(
    "Distrato Bruno Santos de Castro - 25.06.2026",
)


def is_controle_pilot_create_allowed(*, document_name: str) -> bool:
    """True quando a criação está liberada mesmo com ``CONTROLE_PAUSE_CREATE``."""
    normalized = normalize_controle_title(document_name)
    return normalized == BRUNO_DISTRATO_V2_NORMALIZED


def controle_may_create_new_item(
    *,
    document_name: str,
    allow_create: bool | None = None,
) -> bool:
    """Criação de par Jan/Luciano permitida para este documento."""
    if not is_controle_create_paused(allow_create=allow_create):
        return True
    return is_controle_pilot_create_allowed(document_name=document_name)
