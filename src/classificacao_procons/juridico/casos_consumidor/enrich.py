"""Enriquecimento com KPI Monday e melhor condenação."""

from __future__ import annotations

from decimal import Decimal

from classificacao_procons.juridico.casos_consumidor.models import ConsumerCaseInsight
from classificacao_procons.juridico.casos_consumidor.monday_kpi import (
    KpiProcessRow,
    index_kpi_by_consumer_name,
    index_kpi_by_process,
    load_kpi_process_rows,
)
from classificacao_procons.juridico.monday import _normalize_title


def _best_condemnation(
    *,
    kpi: Decimal | None,
    sentence: Decimal | None,
    deposits: Decimal | None,
) -> Decimal | None:
    for candidate in (kpi, sentence, deposits):
        if candidate is not None and candidate > 0:
            return candidate
    return None


def enrich_cases_with_kpi(
    cases: list[ConsumerCaseInsight],
    *,
    api_token: str | None,
) -> tuple[list[ConsumerCaseInsight], dict[str, KpiProcessRow]]:
    rows = load_kpi_process_rows(api_token=api_token)
    by_process = index_kpi_by_process(rows)
    by_name = index_kpi_by_consumer_name(rows)

    enriched: list[ConsumerCaseInsight] = []
    for case in cases:
        kpi_row: KpiProcessRow | None = None
        for process_number in case.process_numbers:
            kpi_row = by_process.get(process_number)
            if kpi_row:
                break
        if kpi_row is None:
            kpi_row = by_name.get(_normalize_title(case.consumer_folder))

        kpi_condemnation = kpi_row.condemnation_brl if kpi_row else None
        kpi_paid = kpi_row.paid_brl if kpi_row else None
        kpi_result = kpi_row.result_label if kpi_row else None
        best = _best_condemnation(
            kpi=kpi_condemnation,
            sentence=case.condemnation_amount_brl,
            deposits=case.total_judicial_deposits_brl,
        )
        enriched.append(
            ConsumerCaseInsight(
                consumer_folder=case.consumer_folder,
                process_numbers=case.process_numbers,
                primary_theme=case.primary_theme,
                secondary_themes=case.secondary_themes,
                theme_confidence=case.theme_confidence,
                theme_evidence=case.theme_evidence,
                total_judicial_deposits_brl=case.total_judicial_deposits_brl,
                deposit_records_count=case.deposit_records_count,
                condemnation_amount_brl=case.condemnation_amount_brl,
                has_sentence_pdf=case.has_sentence_pdf,
                complaint_excerpt=case.complaint_excerpt,
                kpi_condemnation_brl=kpi_condemnation,
                kpi_paid_brl=kpi_paid,
                kpi_result=kpi_result,
                best_condemnation_brl=best,
            ),
        )
    return enriched, by_process
