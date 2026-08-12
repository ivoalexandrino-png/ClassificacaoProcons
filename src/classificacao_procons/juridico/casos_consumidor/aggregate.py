"""Agregação por número de processo (CNJ)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from classificacao_procons.juridico.casos_consumidor.models import CaseTheme, ConsumerCaseInsight
from classificacao_procons.juridico.casos_consumidor.monday_kpi import KpiProcessRow


@dataclass(frozen=True)
class ProcessCaseRow:
    process_number: str
    consumer_folders: tuple[str, ...]
    primary_theme: CaseTheme
    total_judicial_deposits_brl: Decimal | None
    deposit_line_count: int
    condemnation_sentence_brl: Decimal | None
    kpi_condemnation_brl: Decimal | None
    kpi_paid_brl: Decimal | None
    kpi_result: str | None
    best_condemnation_brl: Decimal | None


def _parse_amount(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


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


def build_process_rows(
    *,
    cases: list[ConsumerCaseInsight],
    deposits_json_path: Path,
    kpi_by_process: dict[str, KpiProcessRow],
) -> list[ProcessCaseRow]:
    case_by_consumer = {case.consumer_folder: case for case in cases}
    buckets: dict[str, dict] = {}

    def bucket_for(process_number: str) -> dict:
        if process_number not in buckets:
            buckets[process_number] = {
                "consumers": set(),
                "deposit_sum": Decimal("0"),
                "deposit_lines": 0,
                "sentence": None,
                "theme": CaseTheme.OUTROS,
            }
        return buckets[process_number]

    if deposits_json_path.exists():
        payload = json.loads(deposits_json_path.read_text(encoding="utf-8"))
        for line in payload.get("records", []):
            process_number = line.get("process_number")
            if not process_number:
                continue
            consumer = str(line.get("consumer_folder", "")).strip()
            amount = _parse_amount(line.get("amount_brl"))
            data = bucket_for(str(process_number))
            if consumer:
                data["consumers"].add(consumer)
            if amount:
                data["deposit_sum"] += amount
            data["deposit_lines"] += 1
            case = case_by_consumer.get(consumer)
            if case and case.primary_theme != CaseTheme.OUTROS:
                data["theme"] = case.primary_theme

    for case in cases:
        for process_number in case.process_numbers:
            data = bucket_for(process_number)
            data["consumers"].add(case.consumer_folder)
            if case.primary_theme != CaseTheme.OUTROS:
                data["theme"] = case.primary_theme
            if case.condemnation_amount_brl:
                data["sentence"] = case.condemnation_amount_brl

    for process_number in kpi_by_process:
        bucket_for(process_number)

    rows: list[ProcessCaseRow] = []
    for process_number, data in sorted(buckets.items()):
        kpi = kpi_by_process.get(process_number)
        deposit_sum = data["deposit_sum"] if data["deposit_sum"] > 0 else None
        kpi_condemnation = kpi.condemnation_brl if kpi else None
        rows.append(
            ProcessCaseRow(
                process_number=process_number,
                consumer_folders=tuple(sorted(data["consumers"])),
                primary_theme=data["theme"],
                total_judicial_deposits_brl=deposit_sum,
                deposit_line_count=data["deposit_lines"],
                condemnation_sentence_brl=data["sentence"],
                kpi_condemnation_brl=kpi_condemnation,
                kpi_paid_brl=kpi.paid_brl if kpi else None,
                kpi_result=kpi.result_label if kpi else None,
                best_condemnation_brl=_best_condemnation(
                    kpi=kpi_condemnation,
                    sentence=data["sentence"],
                    deposits=deposit_sum,
                ),
            ),
        )
    return rows
