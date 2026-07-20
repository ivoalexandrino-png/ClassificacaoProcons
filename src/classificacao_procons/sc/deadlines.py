"""Prazos para reclamações do Procon SC (SSP)."""

from __future__ import annotations

from datetime import date, timedelta

from classificacao_procons.juridico.prazos import add_business_days

SC_PROCON_RESPONSE_BUSINESS_DAYS = 20
SC_SAC_DAYS = 5
SC_LEGAL_OFFSET_DAYS = 1


def calculate_sc_deadlines(
    *,
    base_date: date | None = None,
    received_date: date | None = None,
) -> tuple[date, date, date | None]:
    """SC: SAC +5 dias; jurídico +1 após SAC; Procon = +20 dias úteis do recebimento."""
    start = base_date or date.today()
    sac_deadline = start + timedelta(days=SC_SAC_DAYS)
    legal_deadline = sac_deadline + timedelta(days=SC_LEGAL_OFFSET_DAYS)
    procon_deadline = None
    if received_date is not None:
        procon_deadline = add_business_days(received_date, SC_PROCON_RESPONSE_BUSINESS_DAYS)
    return sac_deadline, legal_deadline, procon_deadline
