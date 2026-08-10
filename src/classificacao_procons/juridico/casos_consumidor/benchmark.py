"""Benchmark de casos semelhantes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from classificacao_procons.juridico.casos_consumidor.models import CaseTheme, ConsumerCaseInsight
from classificacao_procons.juridico.casos_consumidor.themes import classify_theme_from_text


@dataclass(frozen=True)
class BenchmarkStats:
    primary_theme: CaseTheme
    matched_cases: int
    with_deposits: int
    median_deposits_brl: Decimal | None
    p90_deposits_brl: Decimal | None
    max_deposits_brl: Decimal | None
    with_condemnation_value: int
    median_condemnation_brl: Decimal | None
    sample_consumers: tuple[str, ...]


def _percentile(values: list[Decimal], pct: float) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100) * (len(ordered) - 1)))))
    return ordered[index]


def _deposit_value(case: ConsumerCaseInsight) -> Decimal | None:
    if case.total_judicial_deposits_brl is None:
        return None
    if case.total_judicial_deposits_brl <= 0:
        return None
    return case.total_judicial_deposits_brl


def _financial_exposure(case: ConsumerCaseInsight) -> Decimal | None:
    if case.best_condemnation_brl is not None and case.best_condemnation_brl > 0:
        return case.best_condemnation_brl
    return _deposit_value(case)


def benchmark_similar_cases(
    *,
    complaint_text: str,
    cases: list[ConsumerCaseInsight],
    include_secondary: bool = True,
    max_samples: int = 5,
) -> BenchmarkStats:
    primary, secondary, _confidence = classify_theme_from_text(complaint_text)
    themes = {primary}
    if include_secondary:
        themes.update(secondary)

    matched = [
        case
        for case in cases
        if case.primary_theme in themes
        or (include_secondary and any(theme in themes for theme in case.secondary_themes))
    ]
    deposit_values = [value for case in matched if (value := _financial_exposure(case)) is not None]
    condemnation_values = [
        case.best_condemnation_brl or case.condemnation_amount_brl or case.kpi_condemnation_brl
        for case in matched
        if (case.best_condemnation_brl or case.condemnation_amount_brl or case.kpi_condemnation_brl)
    ]
    condemnation_values = [value for value in condemnation_values if value and value > 0]

    ranked_samples = sorted(
        matched,
        key=lambda case: _financial_exposure(case) or Decimal("0"),
        reverse=True,
    )
    samples = tuple(case.consumer_folder for case in ranked_samples[:max_samples])

    median_deposits = Decimal(str(median(deposit_values))) if deposit_values else None
    return BenchmarkStats(
        primary_theme=primary,
        matched_cases=len(matched),
        with_deposits=len(deposit_values),
        median_deposits_brl=median_deposits,
        p90_deposits_brl=_percentile(deposit_values, 90),
        max_deposits_brl=max(deposit_values) if deposit_values else None,
        with_condemnation_value=len(condemnation_values),
        median_condemnation_brl=(
            Decimal(str(median(condemnation_values))) if condemnation_values else None
        ),
        sample_consumers=samples,
    )
