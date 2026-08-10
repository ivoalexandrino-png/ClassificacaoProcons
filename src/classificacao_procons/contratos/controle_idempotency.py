"""Chaves idempotentes para mutations do Monday (create_item no Controle)."""

from __future__ import annotations

ControleTrackName = str  # "jan" | "luciano"


def build_controle_create_idempotency_key(
    *,
    autentique_document_id: str,
    track: ControleTrackName,
) -> str:
    """Chave estável ``controle:{document_id}:{track}`` para Idempotency-Key do Monday."""
    doc = autentique_document_id.casefold().strip()
    track_key = track.casefold().strip()
    if not doc or track_key not in ("jan", "luciano"):
        raise ValueError("autentique_document_id e track jan|luciano são obrigatórios.")
    return f"controle:{doc}:{track_key}"
