"""Estado terminal do documento no Autentique (recusa / bloqueio)."""

from __future__ import annotations

from classificacao_procons.contratos.autentique.client import AutentiqueDocumentSummary
from classificacao_procons.contratos.constants import CONTROLE_STATUS_RECUSADO


def document_is_refused_or_blocked(document: AutentiqueDocumentSummary) -> bool:
    return document.is_signature_refused or document.is_signing_blocked


def resolve_controle_terminal_status(document: AutentiqueDocumentSummary) -> str | None:
    """Status Monday quando o fluxo no Autentique não pode continuar."""
    if document.is_signature_refused or document.is_signing_blocked:
        return CONTROLE_STATUS_RECUSADO
    return None
