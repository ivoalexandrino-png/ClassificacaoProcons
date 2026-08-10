"""Cruzamento custas × depósitos × base de cálculo (auditoria de valores)."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


@dataclass(frozen=True)
class CustasReconcileRow:
    consumer_folder: str
    drive_path: str
    process_number: str | None
    fee_type: str
    amount_brl: Decimal | None
    reference_base_brl: Decimal | None
    deposits_same_cnj_brl: Decimal | None
    deposit_line_count: int
    amount_suspect: bool
    suspect_reason: str | None


def _parse_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _load_deposits_by_cnj(path: Path) -> dict[str, list[dict[str, str]]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    lines = payload.get("records", payload if isinstance(payload, list) else [])
    by_cnj: dict[str, list[dict[str, str]]] = {}
    for line in lines:
        if not isinstance(line, dict):
            continue
        cnj = str(line.get("process_number") or "").strip()
        if not cnj:
            continue
        by_cnj.setdefault(cnj, []).append(line)
    return by_cnj


def _suspect_reason(
    *,
    amount: Decimal | None,
    reference_base: Decimal | None,
    deposits_sum: Decimal | None,
) -> tuple[bool, str | None]:
    if amount is None:
        return False, None
    if reference_base is not None and amount == reference_base:
        return True, "amount_equals_reference_base"
    if reference_base is not None and amount >= reference_base * Decimal("0.95"):
        return True, "amount_near_reference_base"
    if (
        deposits_sum is not None
        and amount > deposits_sum * Decimal("3")
        and amount > Decimal("2000")
    ):
        return True, "amount_much_higher_than_deposits_same_cnj"
    if amount >= Decimal("10000"):
        return True, "amount_very_high_review_guia"
    return False, None


def build_reconcile_rows(
    *,
    custas_json_path: Path,
    deposits_json_path: Path,
) -> list[CustasReconcileRow]:
    payload = json.loads(custas_json_path.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    deposits_by_cnj = _load_deposits_by_cnj(deposits_json_path)

    rows: list[CustasReconcileRow] = []
    for record in records:
        cnj = str(record.get("process_number") or "").strip() or None
        amount = _parse_decimal(record.get("amount_brl"))
        reference_base = _parse_decimal(record.get("reference_base_brl"))
        dep_lines = deposits_by_cnj.get(cnj or "", [])
        dep_sum = Decimal("0")
        for line in dep_lines:
            part = _parse_decimal(line.get("amount_brl"))
            if part is not None:
                dep_sum += part
        deposits_total = dep_sum if dep_lines else None
        suspect, reason = _suspect_reason(
            amount=amount,
            reference_base=reference_base,
            deposits_sum=deposits_total,
        )
        rows.append(
            CustasReconcileRow(
                consumer_folder=str(record.get("consumer_folder", "")),
                drive_path=str(record.get("drive_path", "")),
                process_number=cnj,
                fee_type=str(record.get("fee_type", "")),
                amount_brl=amount,
                reference_base_brl=reference_base,
                deposits_same_cnj_brl=deposits_total,
                deposit_line_count=len(dep_lines),
                amount_suspect=suspect,
                suspect_reason=reason,
            )
        )
    return rows


def write_reconcile_csv(*, rows: list[CustasReconcileRow], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        "consumer_folder",
        "drive_path",
        "process_number",
        "fee_type",
        "amount_brl",
        "reference_base_brl",
        "deposits_same_cnj_brl",
        "deposit_line_count",
        "amount_suspect",
        "suspect_reason",
    )
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "consumer_folder": row.consumer_folder,
                    "drive_path": row.drive_path,
                    "process_number": row.process_number,
                    "fee_type": row.fee_type,
                    "amount_brl": f"{row.amount_brl:.2f}" if row.amount_brl else "",
                    "reference_base_brl": (
                        f"{row.reference_base_brl:.2f}" if row.reference_base_brl else ""
                    ),
                    "deposits_same_cnj_brl": (
                        f"{row.deposits_same_cnj_brl:.2f}" if row.deposits_same_cnj_brl else ""
                    ),
                    "deposit_line_count": row.deposit_line_count,
                    "amount_suspect": "true" if row.amount_suspect else "false",
                    "suspect_reason": row.suspect_reason,
                }
            )
