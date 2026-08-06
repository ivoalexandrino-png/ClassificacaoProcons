"""Escopo do quadro Controle Assinaturas (filas ativas vs histórico)."""

from __future__ import annotations

import unicodedata

_PENDING_JAN_KEY = "contratos pendentes de assinatura jan"
_PENDING_LUCIANO_KEY = "contratos pendentes de assinatura luciano"


def _normalize_group_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char)).strip()


def is_controle_pending_track_group_title(group_title: str | None) -> bool:
    """Grupos onde Jan/Luciano assinam (exclui Assinados, Recusado, Pendente Fornecedor)."""
    key = _normalize_group_title(group_title or "")
    return key in (_PENDING_JAN_KEY, _PENDING_LUCIANO_KEY)
