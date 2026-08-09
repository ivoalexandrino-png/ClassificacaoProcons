"""Extração de valor condenatório em sentenças (heurística)."""

from __future__ import annotations

import re
from decimal import Decimal

from classificacao_procons.juridico.depositos.fields import extract_amount_brl

_CONDEMNATION_HINTS = (
    "condeno",
    "julgo procedente",
    "danos morais",
    "danos materiais",
    "valor de",
    "pagamento de",
)


def extract_condemnation_amount_from_sentence(text: str | None) -> Decimal | None:
    if not text or not text.strip():
        return None
    normalized = text.casefold()
    if not any(hint in normalized for hint in _CONDEMNATION_HINTS):
        return extract_amount_brl(text)
    chunks = re.split(r"\n\s*\n", text)
    candidate_chunks = [
        chunk for chunk in chunks if any(hint in chunk.casefold() for hint in _CONDEMNATION_HINTS)
    ]
    amounts: list[Decimal] = []
    for chunk in candidate_chunks or [text]:
        amount = extract_amount_brl(chunk)
        if amount is not None:
            amounts.append(amount)
    if not amounts:
        return extract_amount_brl(text)
    return max(amounts)
