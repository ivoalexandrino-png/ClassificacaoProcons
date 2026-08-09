"""Extração de campos estruturados a partir do texto."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_CNJ_PATTERN = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
_AMOUNT_PATTERN = re.compile(
    r"R\$\s*([\d]{1,3}(?:\.[\d]{3})*,\d{2}|\d+,\d{2})",
    flags=re.IGNORECASE,
)
_BRL_AMOUNT = re.compile(r"([\d]{1,3}(?:\.[\d]{3})*,\d{2})")
_VALUE_LABEL_PATTERN = re.compile(
    r"(?:valor do (?:pagamento|boleto)|valor do pagamento|valor do boleto)"
    r"(?:\s*\(r\$\))?\s*:?\s*([\d]{1,3}(?:\.[\d]{3})*,\d{2})",
    flags=re.IGNORECASE,
)
_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(\d{2}/\d{2}/\d{4})\b"),
    re.compile(r"\b(\d{2}-\d{2}-\d{4})\b"),
)

_MIN_JUDICIAL_AMOUNT = Decimal("10")
_MAX_JUDICIAL_AMOUNT = Decimal("500000")


def extract_process_number(text: str) -> str | None:
    match = _CNJ_PATTERN.search(text)
    return match.group(0) if match else None


def _parse_brl_amount(raw: str) -> Decimal | None:
    cleaned = raw.strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _collect_amount_candidates(text: str) -> list[Decimal]:
    amounts: list[Decimal] = []
    for match in _AMOUNT_PATTERN.finditer(text):
        parsed = _parse_brl_amount(match.group(1))
        if parsed is not None and parsed > 0:
            amounts.append(parsed)
    for match in _VALUE_LABEL_PATTERN.finditer(text):
        parsed = _parse_brl_amount(match.group(1))
        if parsed is not None and parsed > 0:
            amounts.append(parsed)
    if "deposito judicial" in text.casefold() or "depósito judicial" in text.casefold():
        for match in _BRL_AMOUNT.finditer(text):
            parsed = _parse_brl_amount(match.group(1))
            if parsed is not None and parsed > 0:
                amounts.append(parsed)
    return amounts


def extract_amount_brl(text: str) -> Decimal | None:
    amounts = _collect_amount_candidates(text)
    if not amounts:
        return None
    in_range = [
        amount for amount in amounts if _MIN_JUDICIAL_AMOUNT <= amount <= _MAX_JUDICIAL_AMOUNT
    ]
    pool = in_range if in_range else amounts
    return max(pool)


def extract_payment_date(text: str) -> str | None:
    payment_label = re.search(
        r"data de pagamento\s*:?\s*(\d{2}/\d{2}/\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if payment_label:
        return payment_label.group(1)
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None
