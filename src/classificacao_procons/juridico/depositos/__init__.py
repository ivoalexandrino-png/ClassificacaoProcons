"""Inventário de depósitos judiciais a partir de PDFs no Google Drive."""

from classificacao_procons.juridico.depositos.models import DepositScanResult, JudicialDepositRecord
from classificacao_procons.juridico.depositos.pipeline import scan_consumer_deposits

__all__ = [
    "DepositScanResult",
    "JudicialDepositRecord",
    "scan_consumer_deposits",
]
