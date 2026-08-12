"""Status e datas do Controle Assinaturas por fila (Jan/Luciano) vs Autentique."""

from __future__ import annotations

from datetime import date, datetime

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.constants import (
    CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
    CONTROLE_STATUS_AGUARDANDO_OUTROS,
    CONTROLE_STATUS_ASSINADO,
)
from classificacao_procons.contratos.controle_autentique_terminal import (
    resolve_controle_terminal_status,
)
from classificacao_procons.contratos.signer_identity import (
    find_jan_signer,
    find_luciano_signer,
)


def parse_autentique_signature_date(value: str | None) -> date | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    normalized = cleaned.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def _internal_signer_signed(
    document: AutentiqueDocumentSummary,
    *,
    track: str,
) -> bool:
    if track == "jan":
        signer = find_jan_signer(document.signatures)
    elif track == "luciano":
        signer = find_luciano_signer(document.signatures)
    else:
        return False
    return bool(signer and signer.signed_at)


def resolve_controle_status_for_track(
    document: AutentiqueDocumentSummary,
    *,
    track: str,
) -> str:
    """Status do item Monday da fila ``jan`` ou ``luciano`` conforme o Autentique."""
    terminal = resolve_controle_terminal_status(document)
    if terminal is not None:
        return terminal
    if track not in ("jan", "luciano"):
        return resolve_controle_status_document(document)
    if _internal_signer_signed(document, track=track):
        return CONTROLE_STATUS_ASSINADO
    return CONTROLE_STATUS_AGUARDANDO_ASSINATURA


def resolve_signed_at_for_track(
    document: AutentiqueDocumentSummary,
    *,
    track: str,
) -> date | None:
    """Data de assinatura só do signatário interno da fila (não de terceiros)."""
    if track == "jan":
        signer: AutentiqueSigner | None = find_jan_signer(document.signatures)
    elif track == "luciano":
        signer = find_luciano_signer(document.signatures)
    else:
        signer = None
    if signer and signer.signed_at:
        return parse_autentique_signature_date(signer.signed_at)
    return None


def resolve_controle_status_document(document: AutentiqueDocumentSummary) -> str:
    """Status agregado (legado) quando a fila não está identificada."""
    terminal = resolve_controle_terminal_status(document)
    if terminal is not None:
        return terminal
    if document.is_fully_signed:
        return CONTROLE_STATUS_ASSINADO
    signed_count = sum(1 for signer in document.signatures if signer.signed_at)
    if signed_count > 0:
        return CONTROLE_STATUS_AGUARDANDO_OUTROS
    return CONTROLE_STATUS_AGUARDANDO_ASSINATURA


def resolve_signed_at_document(document: AutentiqueDocumentSummary) -> date | None:
    """Última assinatura entre todos os signatários (uso legado)."""
    signed_dates: list[date] = []
    for signer in document.signatures:
        if not signer.signed_at:
            continue
        parsed = parse_autentique_signature_date(signer.signed_at)
        if parsed is not None:
            signed_dates.append(parsed)
    if not signed_dates:
        return None
    return max(signed_dates)
