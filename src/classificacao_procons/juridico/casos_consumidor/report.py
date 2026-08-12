"""Exportação de insights de casos."""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

from classificacao_procons.juridico.casos_consumidor.aggregate import ProcessCaseRow
from classificacao_procons.juridico.casos_consumidor.models import (
    CaseTheme,
    CasosScanResult,
    ConsumerCaseInsight,
)

_CSV_FIELDS = (
    "consumer_folder",
    "process_numbers",
    "primary_theme",
    "secondary_themes",
    "theme_confidence",
    "theme_evidence",
    "total_judicial_deposits_brl",
    "deposit_records_count",
    "condemnation_amount_brl",
    "kpi_condemnation_brl",
    "kpi_paid_brl",
    "kpi_result",
    "best_condemnation_brl",
    "has_sentence_pdf",
    "complaint_excerpt",
)


def _case_to_dict(case: ConsumerCaseInsight) -> dict[str, str | int | None]:
    return {
        "consumer_folder": case.consumer_folder,
        "process_numbers": ";".join(case.process_numbers),
        "primary_theme": case.primary_theme.value,
        "secondary_themes": ";".join(theme.value for theme in case.secondary_themes),
        "theme_confidence": case.theme_confidence,
        "theme_evidence": case.theme_evidence,
        "total_judicial_deposits_brl": (
            f"{case.total_judicial_deposits_brl:.2f}"
            if case.total_judicial_deposits_brl is not None
            else None
        ),
        "deposit_records_count": case.deposit_records_count,
        "condemnation_amount_brl": (
            f"{case.condemnation_amount_brl:.2f}"
            if case.condemnation_amount_brl is not None
            else None
        ),
        "kpi_condemnation_brl": (
            f"{case.kpi_condemnation_brl:.2f}" if case.kpi_condemnation_brl is not None else None
        ),
        "kpi_paid_brl": f"{case.kpi_paid_brl:.2f}" if case.kpi_paid_brl is not None else None,
        "kpi_result": case.kpi_result,
        "best_condemnation_brl": (
            f"{case.best_condemnation_brl:.2f}" if case.best_condemnation_brl is not None else None
        ),
        "has_sentence_pdf": "yes" if case.has_sentence_pdf else "no",
        "complaint_excerpt": case.complaint_excerpt,
    }


def write_casos_csv(*, result: CasosScanResult, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_CSV_FIELDS))
        writer.writeheader()
        for case in result.cases:
            writer.writerow(_case_to_dict(case))


def write_casos_json(*, result: CasosScanResult, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "consumers_scanned": result.consumers_scanned,
        "consumers_with_deposits": result.consumers_with_deposits,
        "cases": [_case_to_dict(case) for case in result.cases],
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cases_from_json(path: Path) -> list[ConsumerCaseInsight]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases: list[ConsumerCaseInsight] = []
    for row in payload.get("cases", []):
        deposits = row.get("total_judicial_deposits_brl")
        condemnation = row.get("condemnation_amount_brl")
        secondary_raw = row.get("secondary_themes") or ""
        secondary = tuple(
            CaseTheme(value)
            for value in secondary_raw.split(";")
            if value.strip() in CaseTheme._value2member_map_
        )
        process_raw = row.get("process_numbers") or ""
        cases.append(
            ConsumerCaseInsight(
                consumer_folder=str(row["consumer_folder"]),
                process_numbers=tuple(
                    part.strip() for part in process_raw.split(";") if part.strip()
                ),
                primary_theme=CaseTheme(str(row["primary_theme"])),
                secondary_themes=secondary,
                theme_confidence=str(row.get("theme_confidence", "low")),
                theme_evidence=row.get("theme_evidence"),
                total_judicial_deposits_brl=Decimal(deposits) if deposits else None,
                deposit_records_count=int(row.get("deposit_records_count") or 0),
                condemnation_amount_brl=Decimal(condemnation) if condemnation else None,
                has_sentence_pdf=str(row.get("has_sentence_pdf", "")).casefold() == "yes",
                complaint_excerpt=row.get("complaint_excerpt"),
                kpi_condemnation_brl=_decimal_or_none(row.get("kpi_condemnation_brl")),
                kpi_paid_brl=_decimal_or_none(row.get("kpi_paid_brl")),
                kpi_result=row.get("kpi_result"),
                best_condemnation_brl=_decimal_or_none(row.get("best_condemnation_brl")),
            ),
        )
    return cases


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


_PROCESS_FIELDS = (
    "process_number",
    "consumer_folders",
    "primary_theme",
    "total_judicial_deposits_brl",
    "deposit_line_count",
    "condemnation_sentence_brl",
    "kpi_condemnation_brl",
    "kpi_paid_brl",
    "kpi_result",
    "best_condemnation_brl",
)


def write_process_csv(*, rows: list[ProcessCaseRow], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_PROCESS_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "process_number": row.process_number,
                    "consumer_folders": ";".join(row.consumer_folders),
                    "primary_theme": row.primary_theme.value,
                    "total_judicial_deposits_brl": (
                        f"{row.total_judicial_deposits_brl:.2f}"
                        if row.total_judicial_deposits_brl is not None
                        else None
                    ),
                    "deposit_line_count": row.deposit_line_count,
                    "condemnation_sentence_brl": (
                        f"{row.condemnation_sentence_brl:.2f}"
                        if row.condemnation_sentence_brl is not None
                        else None
                    ),
                    "kpi_condemnation_brl": (
                        f"{row.kpi_condemnation_brl:.2f}"
                        if row.kpi_condemnation_brl is not None
                        else None
                    ),
                    "kpi_paid_brl": (
                        f"{row.kpi_paid_brl:.2f}" if row.kpi_paid_brl is not None else None
                    ),
                    "kpi_result": row.kpi_result,
                    "best_condemnation_brl": (
                        f"{row.best_condemnation_brl:.2f}"
                        if row.best_condemnation_brl is not None
                        else None
                    ),
                },
            )
