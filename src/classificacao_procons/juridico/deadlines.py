"""Cálculo de prazos processuais em dias úteis (CPC/2015, art. 219).

Regras adotadas (simplificadas e documentadas para revisão pelo jurídico):

- Prazos processuais são contados em **dias úteis** (art. 219). Prazos de
  direito material continuam em dias corridos — use ``business_days=False``.
- Exclui-se o dia do começo e inclui-se o dia do vencimento (art. 224).
- A contagem inicia-se no **primeiro dia útil seguinte** à data de publicação
  (art. 224, §§ 2º e 3º).
- Sábados, domingos e feriados informados em ``holidays`` não são contados.

Feriados forenses variam por tribunal/comarca; por isso ``holidays`` é um
parâmetro explícito. Sem feriados informados, apenas fins de semana são
descartados.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta


def is_business_day(day: date, holidays: frozenset[date]) -> bool:
    """Retorna True se ``day`` é dia útil (não é fim de semana nem feriado)."""
    if day.weekday() >= 5:  # 5 = sábado, 6 = domingo
        return False
    return day not in holidays


def next_business_day(day: date, holidays: frozenset[date]) -> date:
    """Retorna o próximo dia útil estritamente após ``day``."""
    candidate = day + timedelta(days=1)
    while not is_business_day(candidate, holidays):
        candidate += timedelta(days=1)
    return candidate


def add_business_days(start: date, days: int, holidays: frozenset[date]) -> date:
    """Soma ``days`` dias úteis a partir de ``start`` (exclusive).

    ``add_business_days(sexta, 1)`` retorna a segunda-feira seguinte.
    """
    if days <= 0:
        raise ValueError("O número de dias úteis deve ser positivo.")
    current = start
    remaining = days
    while remaining > 0:
        current = next_business_day(current, holidays)
        remaining -= 1
    return current


def calculate_prazo_final(
    *,
    publication_date: date,
    dias: int,
    business_days: bool = True,
    holidays: Iterable[date] | None = None,
) -> date:
    """Calcula a data final de um prazo processual.

    A contagem começa no primeiro dia útil seguinte à ``publication_date`` e
    inclui o dia do vencimento. Se o vencimento cair em dia não útil, é
    prorrogado para o próximo dia útil (art. 224, § 1º).
    """
    if dias <= 0:
        raise ValueError("O prazo em dias deve ser positivo.")

    holiday_set = frozenset(holidays or ())

    if not business_days:
        start = publication_date + timedelta(days=1)
        deadline = start + timedelta(days=dias - 1)
        while not is_business_day(deadline, holiday_set):
            deadline += timedelta(days=1)
        return deadline

    return add_business_days(publication_date, dias, holiday_set)
