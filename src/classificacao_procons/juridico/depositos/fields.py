"""Extração de campos estruturados a partir do texto."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_CNJ_PATTERN = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
_AMOUNT_PATTERN = re.compile(
    r"R\$\s*([\d]{1,3}(?:\.[\d]{3})*,\d{2}|\d+,\d{2})",
    flags=re.IGNORECASE,
)
_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(\d{2}/\d{2}/\d{4})\b"),
    re.compile(r"\b(\d{2}-\d{2}-\d{4})\b"),
)


def extract_process_number(text: str) -> str | None:
    match = _CNJ_PATTERN.search(text)
    return match.group(0) if match else None


def _parse_brl_amount(raw: str) -> Decimal | None:
    cleaned = raw.strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def extract_amount_brl(text: str) -> Decimal | None:
    amounts: list[Decimal] = []
    for match in _AMOUNT_PATTERN.finditer(text):
        parsed = _parse_brl_amount(match.group(1))
        if parsed is not None and parsed > 0:
            amounts.append(parsed)
    if not amounts:
        return None
    return max(amounts)


def extract_payment_date(text: str) -> str | None:
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None
