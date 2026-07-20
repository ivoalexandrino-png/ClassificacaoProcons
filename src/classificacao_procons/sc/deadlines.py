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
    """SC: SAC +5 dias e jurídico +1 a partir do recebimento; Procon +20 dias úteis."""
    receipt = received_date or base_date or date.today()
    sac_deadline = receipt + timedelta(days=SC_SAC_DAYS)
    legal_deadline = sac_deadline + timedelta(days=SC_LEGAL_OFFSET_DAYS)
    procon_deadline = add_business_days(receipt, SC_PROCON_RESPONSE_BUSINESS_DAYS)
    return sac_deadline, legal_deadline, procon_deadline
