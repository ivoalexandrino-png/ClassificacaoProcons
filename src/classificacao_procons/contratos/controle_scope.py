"""Escopo do documento no fluxo Controle Assinaturas Contratos (sem LLM)."""

from __future__ import annotations

import re
from enum import StrEnum

from classificacao_procons.contratos.autentique.client import AutentiqueDocumentSummary
from classificacao_procons.contratos.controle_dedup import normalize_controle_title

ControleTrackName = str  # "jan" | "luciano"


class ControleScopeClassification(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    MANUAL_REVIEW = "manual_review"


_HR_NON_CONTRACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bferias\b|\bférias\b", re.IGNORECASE),
    re.compile(r"\brescis", re.IGNORECASE),
    re.compile(r"\baviso\b.*\bferias\b|\baviso\b.*\bférias\b", re.IGNORECASE),
    re.compile(r"\bdeclarac", re.IGNORECASE),
    re.compile(r"\bplano\b.*\bsaude\b|\bplano\b.*\bsaúde\b", re.IGNORECASE),
    re.compile(r"\binclusao\b.*\bplano\b|\binclusão\b.*\bplano\b", re.IGNORECASE),
    re.compile(r"\bcodigo\b.*\bconduta\b|\bcódigo\b.*\bconduta\b", re.IGNORECASE),
    re.compile(r"\badmissao\b|\badmissão\b", re.IGNORECASE),
    re.compile(r"\bficha\b.*\bregistro\b", re.IGNORECASE),
    re.compile(r"\btce\b", re.IGNORECASE),
    re.compile(r"\bcarta\b.*\binclus", re.IGNORECASE),
)

_CONTRACT_DOMAIN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcontrato\b.*\bb2b\b", re.IGNORECASE),
    re.compile(r"\bcontrato\b.*\bcomercial\b", re.IGNORECASE),
    re.compile(r"\bcontrato\b.*\bfornec", re.IGNORECASE),
    re.compile(r"\bcontrato\b.*\bprestac", re.IGNORECASE),
    re.compile(r"\bcontrato\b.*\bparceria\b", re.IGNORECASE),
    re.compile(r"\bminuta\b", re.IGNORECASE),
    re.compile(r"\bacordo\b", re.IGNORECASE),
    re.compile(r"\bnda\b", re.IGNORECASE),
)

_SUPPLEMENTAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\baditivo\b", re.IGNORECASE),
    re.compile(r"\bdistrato\b", re.IGNORECASE),
    re.compile(r"\bprocurac", re.IGNORECASE),
)


def _title_matches_any(title: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(title) for pattern in patterns)


def classify_controle_scope(
    document: AutentiqueDocumentSummary,
    *,
    expected_tracks: frozenset[ControleTrackName],
) -> tuple[ControleScopeClassification, str]:
    """Classifica se o documento pertence ao Controle Contratos (determinístico)."""
    if not expected_tracks:
        if not document.signatures:
            return (
                ControleScopeClassification.MANUAL_REVIEW,
                "no_signatures_no_internal_signer",
            )
        return ControleScopeClassification.INELIGIBLE, "no_internal_signer"

    normalized = normalize_controle_title(document.name)

    if _title_matches_any(normalized, _HR_NON_CONTRACT_PATTERNS):
        return ControleScopeClassification.INELIGIBLE, "hr_non_contract_domain"

    if _title_matches_any(normalized, _SUPPLEMENTAL_PATTERNS):
        return ControleScopeClassification.ELIGIBLE, "supplemental_document"

    if _title_matches_any(normalized, _CONTRACT_DOMAIN_PATTERNS):
        return ControleScopeClassification.ELIGIBLE, "contract_domain"

    if re.search(r"\bcontrato\b", normalized, re.IGNORECASE):
        return ControleScopeClassification.MANUAL_REVIEW, "generic_contrato_title"

    return ControleScopeClassification.MANUAL_REVIEW, "uncertain_domain"
