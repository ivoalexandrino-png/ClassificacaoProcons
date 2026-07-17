"""Contagem de prazos processuais em dias úteis (CPC, arts. 219 e 224)."""

from __future__ import annotations

from datetime import date, timedelta

SATURDAY = 5


def is_business_day(day: date) -> bool:
    """Sábados e domingos não contam; feriados exigem calendário do tribunal."""
    return day.weekday() < SATURDAY


def next_business_day(day: date) -> date:
    current = day
    while not is_business_day(current):
        current += timedelta(days=1)
    return current


def add_business_days(start: date, days: int) -> date:
    """
    Termo final de prazo em dias úteis.

    A contagem exclui o dia do começo (CPC art. 224): o primeiro dia contado
    é o primeiro dia útil seguinte a `start`.
    """
    if days < 0:
        raise ValueError("Prazo em dias não pode ser negativo.")
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if is_business_day(current):
            remaining -= 1
    return next_business_day(current)


def add_calendar_days(start: date, days: int) -> date:
    """Prazo em dias corridos; termo final prorrogado para o dia útil seguinte."""
    if days < 0:
        raise ValueError("Prazo em dias não pode ser negativo.")
    return next_business_day(start + timedelta(days=days))


def compute_due_date(
    *,
    base_date: date,
    deadline_days: int | None,
    in_business_days: bool = True,
    explicit_date: date | None = None,
) -> date | None:
    """Data-limite da providência: data explícita vence contagem por dias."""
    if explicit_date is not None:
        return explicit_date
    if deadline_days is None:
        return None
    if in_business_days:
        return add_business_days(base_date, deadline_days)
    return add_calendar_days(base_date, deadline_days)
