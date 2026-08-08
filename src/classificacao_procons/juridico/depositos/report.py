"""Exportação CSV/JSON do relatório de depósitos."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from classificacao_procons.juridico.depositos.models import DepositScanResult, JudicialDepositRecord

_CSV_FIELDS = (
    "consumer_folder",
    "drive_file_id",
    "drive_path",
    "drive_url",
    "document_kind",
    "process_number",
    "amount_brl",
    "payment_date",
    "deposit_purpose",
    "extraction_method",
    "confidence",
    "notes",
)


def _record_to_dict(record: JudicialDepositRecord) -> dict[str, str | None]:
    amount: str | None = None
    if record.amount_brl is not None:
        amount = f"{record.amount_brl:.2f}"
    return {
        "consumer_folder": record.consumer_folder,
        "drive_file_id": record.drive_file_id,
        "drive_path": record.drive_path,
        "drive_url": record.drive_url,
        "document_kind": record.document_kind.value,
        "process_number": record.process_number,
        "amount_brl": amount,
        "payment_date": record.payment_date,
        "deposit_purpose": record.deposit_purpose.value,
        "extraction_method": record.extraction_method,
        "confidence": record.confidence.value,
        "notes": record.notes,
    }


def write_deposits_csv(*, result: DepositScanResult, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_CSV_FIELDS))
        writer.writeheader()
        for record in result.records:
            writer.writerow(_record_to_dict(record))


def write_scan_summary_json(*, result: DepositScanResult, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "consumers_scanned": result.consumers_scanned,
        "pdfs_seen": result.pdfs_seen,
        "pdfs_analyzed": result.pdfs_analyzed,
        "pdfs_skipped_path": result.pdfs_skipped_path,
        "deposit_records": len(result.records),
        "records": [_record_to_dict(record) for record in result.records],
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
