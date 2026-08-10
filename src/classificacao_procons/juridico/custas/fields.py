"""Extração de valores de guias de custas (evita valor da causa/condenação)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from classificacao_procons.juridico.depositos.fields import (
    _AMOUNT_PATTERN,
    _MAX_JUDICIAL_AMOUNT,
    _MIN_JUDICIAL_AMOUNT,
    _parse_brl_amount,
)

# Valores de referência na guia — não são o pagamento de custas.
_REFERENCE_CONTEXT: tuple[str, ...] = (
    "valor da causa",
    "valor da acao",
    "valor da ação",
    "valor base",
    "valor da condenacao",
    "valor da condenação",
    "valor da execucao",
    "valor da execução",
    "valor da vrc",
)

_PAYMENT_LABEL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:valor\s+total|total\s+geral)\s*:?\s*R\$\s*"
        r"([\d]{1,3}(?:\.[\d]{3})*,\d{2})",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"(?:\(\=\)\s*)?valor\s+(?:do\s+)?documento\s*:?\s*R\$\s*"
        r"([\d]{1,3}(?:\.[\d]{3})*,\d{2})",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"valor\s+cobrado\s*:?\s*R\$\s*([\d]{1,3}(?:\.[\d]{3})*,\d{2})",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"R\$\s*([\d]{1,3}(?:\.[\d]{3})*,\d{2})\s*VALOR\s+TOTAL",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"TOTAL\s*:\s*([\d]{1,3}(?:\.[\d]{3})*,\d{2})",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"TOTAL\s*:\s*\.+\s*([\d]{1,3}(?:\.[\d]{3})*,\d{2})",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"TOTAL\s*\([^)]+\)\s*R\$\s*([\d]{1,3}(?:\.[\d]{3})*,\d{2})",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"Processo\s+[\d.\-]+\s+[\d.]+\s+Moeda.*?\s+Valor\s*R\$\s*"
        r"([\d]{1,3}(?:\.[\d]{3})*,\d{2})",
        flags=re.IGNORECASE | re.DOTALL,
    ),
)


@dataclass(frozen=True)
class CustasAmountExtraction:
    amount_brl: Decimal | None
    reference_base_brl: Decimal | None
    method: str


def _normalize_window(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _in_reference_context(*, text: str, start: int, end: int) -> bool:
    window_start = max(0, start - 90)
    window = _normalize_window(text[window_start:end])
    return any(keyword in window for keyword in _REFERENCE_CONTEXT)


def extract_reference_base_brl(text: str) -> Decimal | None:
    patterns = (
        re.compile(
            r"valor\s+(?:da\s+)?(?:causa|ação|acao|base)\s*:?\s*R\$\s*"
            r"([\d]{1,3}(?:\.[\d]{3})*,\d{2})",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"valor\s+base\s*:?\s*R\$\s*([\d]{1,3}(?:\.[\d]{3})*,\d{2})",
            flags=re.IGNORECASE,
        ),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            parsed = _parse_brl_amount(match.group(1))
            if parsed is not None:
                return parsed
    return None


def _clamp_amount(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if value < _MIN_JUDICIAL_AMOUNT or value > _MAX_JUDICIAL_AMOUNT:
        return None
    return value


def extract_custas_amount_brl(text: str) -> CustasAmountExtraction:
    reference_base = extract_reference_base_brl(text)

    for pattern in _PAYMENT_LABEL_PATTERNS:
        match = pattern.search(text)
        if match:
            amount = _clamp_amount(_parse_brl_amount(match.group(1)))
            if amount is not None:
                return CustasAmountExtraction(
                    amount_brl=amount,
                    reference_base_brl=reference_base,
                    method="custas_label",
                )

    candidates: list[Decimal] = []
    for match in _AMOUNT_PATTERN.finditer(text):
        if _in_reference_context(text=text, start=match.start(), end=match.end()):
            continue
        parsed = _parse_brl_amount(match.group(1))
        if parsed is None or parsed <= 0:
            continue
        if _MIN_JUDICIAL_AMOUNT <= parsed <= _MAX_JUDICIAL_AMOUNT:
            candidates.append(parsed)

    if candidates:
        # Em guias com várias linhas de despesa, o total costuma ser o menor
        # valor “redondo” próximo do boleto, não a soma parcial de uma linha.
        payment_like = sorted(set(candidates))
        amount = payment_like[0]
        if len(payment_like) > 1 and payment_like[-1] > amount * Decimal("5"):
            amount = payment_like[0]
        else:
            amount = min(payment_like)
        return CustasAmountExtraction(
            amount_brl=amount,
            reference_base_brl=reference_base,
            method="custas_filtered_min",
        )

    return CustasAmountExtraction(
        amount_brl=None,
        reference_base_brl=reference_base,
        method="custas_none",
    )
