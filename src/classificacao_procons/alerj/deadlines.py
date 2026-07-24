"""Prazos para reclamações da ALERJ."""

from __future__ import annotations

from datetime import date, timedelta

ALERJ_PROCON_RESPONSE_DAYS = 10
ALERJ_SAC_DAYS = 5
ALERJ_LEGAL_OFFSET_DAYS = 1


def calculate_alerj_deadlines(
    *,
    base_date: date | None = None,
    received_date: date | None = None,
) -> tuple[date, date, date | None]:
    """ALERJ: SAC +5 dias e jurídico +1 a partir do recebimento; Procon +10 dias corridos."""
    receipt = received_date or base_date or date.today()
    sac_deadline = receipt + timedelta(days=ALERJ_SAC_DAYS)
    legal_deadline = sac_deadline + timedelta(days=ALERJ_LEGAL_OFFSET_DAYS)
    procon_deadline = receipt + timedelta(days=ALERJ_PROCON_RESPONSE_DAYS)
    return sac_deadline, legal_deadline, procon_deadline
