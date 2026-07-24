"""Prazos internos para reclamações do Procon Campinas."""

from __future__ import annotations

from datetime import date, timedelta

CAMPINAS_SAC_DAYS = 3
CAMPINAS_LEGAL_OFFSET_DAYS = 1


def calculate_campinas_deadlines(*, base_date: date | None = None) -> tuple[date, date]:
    """Campinas: SAC +3 dias; jurídico +1 dia após o SAC."""
    start = base_date or date.today()
    sac_deadline = start + timedelta(days=CAMPINAS_SAC_DAYS)
    legal_deadline = sac_deadline + timedelta(days=CAMPINAS_LEGAL_OFFSET_DAYS)
    return sac_deadline, legal_deadline
