"""Modelos para análise temática de processos de consumidor."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class CaseTheme(StrEnum):
    RENOVACAO_AUTOMATICA = "renovacao_automatica"
    PROBLEMA_ENTREGA = "problema_entrega"
    PROBLEMA_PAGAMENTO = "problema_pagamento"
    PROBLEMA_CANCELAMENTO = "problema_cancelamento"
    PROBLEMA_EXPERIENCIA = "problema_experiencia"
    OUTROS = "outros"


@dataclass(frozen=True)
class ConsumerCaseInsight:
    consumer_folder: str
    process_numbers: tuple[str, ...]
    primary_theme: CaseTheme
    secondary_themes: tuple[CaseTheme, ...]
    theme_confidence: str
    theme_evidence: str | None
    total_judicial_deposits_brl: Decimal | None
    deposit_records_count: int
    condemnation_amount_brl: Decimal | None
    has_sentence_pdf: bool
    complaint_excerpt: str | None
    kpi_condemnation_brl: Decimal | None = None
    kpi_paid_brl: Decimal | None = None
    kpi_result: str | None = None
    best_condemnation_brl: Decimal | None = None


@dataclass
class CasosScanResult:
    cases: list[ConsumerCaseInsight]
    consumers_scanned: int
    consumers_with_deposits: int
    kpi_by_process: dict | None = None
