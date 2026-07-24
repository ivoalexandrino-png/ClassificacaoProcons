"""Prazos internos para reclamações do Procon Uberlândia."""

from __future__ import annotations

from datetime import date, timedelta

UBERLANDIA_SAC_DAYS = 5
UBERLANDIA_LEGAL_OFFSET_DAYS = 1


def calculate_uberlandia_deadlines(*, base_date: date | None = None) -> tuple[date, date]:
    """Uberlândia: SAC +5 dias; jurídico +1 dia após o SAC (a partir do recebimento)."""
    start = base_date or date.today()
    sac_deadline = start + timedelta(days=UBERLANDIA_SAC_DAYS)
    legal_deadline = sac_deadline + timedelta(days=UBERLANDIA_LEGAL_OFFSET_DAYS)
    return sac_deadline, legal_deadline
