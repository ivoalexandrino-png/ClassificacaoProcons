"""Agregação de custas por número de processo (CNJ)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from classificacao_procons.juridico.custas.models import CourtFeeRecord


@dataclass(frozen=True)
class ProcessCustasRow:
    process_number: str
    consumer_folders: tuple[str, ...]
    total_court_fees_brl: Decimal | None
    fee_line_count: int
    fee_types: tuple[str, ...]


def build_custas_process_rows(*, records: list[CourtFeeRecord]) -> list[ProcessCustasRow]:
    buckets: dict[str, dict] = {}

    def bucket_for(process_number: str) -> dict:
        if process_number not in buckets:
            buckets[process_number] = {
                "consumers": set(),
                "sum": Decimal("0"),
                "lines": 0,
                "types": set(),
            }
        return buckets[process_number]

    for record in records:
        process_number = (record.process_number or "").strip()
        if not process_number:
            continue
        data = bucket_for(process_number)
        data["consumers"].add(record.consumer_folder)
        data["lines"] += 1
        data["types"].add(record.fee_type.value)
        if record.amount_brl is not None:
            data["sum"] += record.amount_brl

    rows: list[ProcessCustasRow] = []
    for process_number in sorted(buckets.keys()):
        data = buckets[process_number]
        total = data["sum"] if data["lines"] and data["sum"] > 0 else None
        rows.append(
            ProcessCustasRow(
                process_number=process_number,
                consumer_folders=tuple(sorted(data["consumers"], key=str.casefold)),
                total_court_fees_brl=total,
                fee_line_count=data["lines"],
                fee_types=tuple(sorted(data["types"])),
            )
        )
    return rows
