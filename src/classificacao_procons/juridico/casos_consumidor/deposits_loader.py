"""Agrega depósitos judiciais por pasta de consumidor."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


@dataclass(frozen=True)
class ConsumerDepositSummary:
    total_brl: Decimal
    record_count: int
    process_numbers: tuple[str, ...]


def load_deposits_by_consumer(path: Path) -> dict[str, ConsumerDepositSummary]:
    if not path.exists():
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records", payload if isinstance(payload, list) else [])
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    counts: dict[str, int] = defaultdict(int)
    processes: dict[str, set[str]] = defaultdict(set)

    for record in records:
        if not isinstance(record, dict):
            continue
        folder = str(record.get("consumer_folder", "")).strip()
        if not folder:
            continue
        counts[folder] += 1
        raw_amount = record.get("amount_brl")
        if raw_amount:
            try:
                totals[folder] += Decimal(str(raw_amount))
            except InvalidOperation:
                pass
        process_number = record.get("process_number")
        if process_number:
            processes[folder].add(str(process_number).strip())

    result: dict[str, ConsumerDepositSummary] = {}
    for folder, count in counts.items():
        total = totals[folder]
        result[folder] = ConsumerDepositSummary(
            total_brl=total,
            record_count=count,
            process_numbers=tuple(sorted(processes[folder])),
        )
    return result
