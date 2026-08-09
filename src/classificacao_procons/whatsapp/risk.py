"""Classificação heurística de risco (jurídico / ambiguidade)."""

from __future__ import annotations

import re
from typing import Literal

RiskTier = Literal["routine", "ambiguous", "legal_high"]

_LEGAL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bprocesso\b",
        r"\bprocon\b",
        r"\bintima[cç][aã]o\b",
        r"\badvogad",
        r"\bju[ií]z\b",
        r"\btribunal\b",
        r"\ba[cç][aã]o\s+judicial\b",
        r"\bcontrato\b",
        r"\bassinatur",
        r"\bmulta\b",
        r"\bindeniza",
        r"\brescis",
        r"\bdemiss",
        r"\btrabalhist",
        r"\breclama[cç][aã]o\s+formal\b",
        r"\bnotifica[cç][aã]o\s+extrajudicial\b",
        r"\bexecu[cç][aã]o\s+fiscal\b",
        r"\bpgfn\b",
        r"\breceita\s+federal\b",
        r"\bdefesa\b.*\b(processo|procon|autua)",
        r"\bprazo\s+legal\b",
        r"\bconfidencial\b.*\b(contrato|acordo|nda)\b",
        r"\bautentique\b",
        r"\bdatajud\b",
    )
)

_AMBIGUOUS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bn[aã]o\s+tenho\s+certeza\b",
        r"\bna\s+d[uú]vida\b",
        r"\bser[aá]\s+que\b",
        r"\btalvez\b",
        r"\bacho\s+que\b",
        r"\bpode\s+ser\s+que\b",
        r"\bdepende\b",
        r"\?{2,}",
        r"\bcomo\s+assim\b",
        r"\bexplica\s+melhor\b",
    )
)


def heuristic_risk_tier(text: str) -> RiskTier | None:
    """Retorna tier se heurística tiver confiança; senão None (deixar LLM decidir)."""
    normalized = text.strip()
    if not normalized:
        return "ambiguous"

    for pattern in _LEGAL_PATTERNS:
        if pattern.search(normalized):
            return "legal_high"

    ambiguous_hits = sum(1 for pattern in _AMBIGUOUS_PATTERNS if pattern.search(normalized))
    if ambiguous_hits >= 2:
        return "ambiguous"
    if ambiguous_hits == 1 and "?" in normalized:
        return "ambiguous"

    return None
