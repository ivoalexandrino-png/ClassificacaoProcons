"""Estado terminal do documento no Autentique (recusa / bloqueio)."""

from __future__ import annotations

from classificacao_procons.contratos.autentique.client import AutentiqueDocumentSummary
from classificacao_procons.contratos.constants import (
    CONTROLE_STATUS_BLOQUEADO,
    CONTROLE_STATUS_RECUSADO,
)


def document_has_terminal_controle_status(document: AutentiqueDocumentSummary) -> bool:
    return resolve_controle_terminal_status(document) is not None


def document_is_refused_or_blocked(document: AutentiqueDocumentSummary) -> bool:
    """Legado: qualquer status terminal (recusado ou bloqueado)."""
    return document_has_terminal_controle_status(document)


def resolve_controle_terminal_status(document: AutentiqueDocumentSummary) -> str | None:
    """Status Monday quando o fluxo no Autentique não pode continuar."""
    if document.is_signature_refused:
        return CONTROLE_STATUS_RECUSADO
    if document.is_signing_blocked:
        return CONTROLE_STATUS_BLOQUEADO
    return None
