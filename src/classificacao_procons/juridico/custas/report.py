"""Exportação CSV/JSON do relatório de custas processuais."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from classificacao_procons.juridico.custas.aggregate import (
    ProcessCustasRow,
    build_custas_process_rows,
)
from classificacao_procons.juridico.custas.models import CourtFeeRecord, CustasScanResult

_CSV_FIELDS = (
    "consumer_folder",
    "drive_file_id",
    "drive_path",
    "drive_url",
    "process_number",
    "amount_brl",
    "reference_base_brl",
    "payment_date",
    "fee_type",
    "extraction_method",
    "confidence",
    "notes",
)

_PROCESS_CSV_FIELDS = (
    "process_number",
    "consumer_folders",
    "total_court_fees_brl",
    "fee_line_count",
    "fee_types",
)


def _record_to_dict(record: CourtFeeRecord) -> dict[str, str | None]:
    amount: str | None = None
    if record.amount_brl is not None:
        amount = f"{record.amount_brl:.2f}"
    reference_base: str | None = None
    if record.reference_base_brl is not None:
        reference_base = f"{record.reference_base_brl:.2f}"
    return {
        "consumer_folder": record.consumer_folder,
        "drive_file_id": record.drive_file_id,
        "drive_path": record.drive_path,
        "drive_url": record.drive_url,
        "process_number": record.process_number,
        "amount_brl": amount,
        "reference_base_brl": reference_base,
        "payment_date": record.payment_date,
        "fee_type": record.fee_type.value,
        "extraction_method": record.extraction_method,
        "confidence": record.confidence.value,
        "notes": record.notes,
    }


def _process_row_to_dict(row: ProcessCustasRow) -> dict[str, str | int | None]:
    total: str | None = None
    if row.total_court_fees_brl is not None:
        total = f"{row.total_court_fees_brl:.2f}"
    return {
        "process_number": row.process_number,
        "consumer_folders": "; ".join(row.consumer_folders),
        "total_court_fees_brl": total,
        "fee_line_count": row.fee_line_count,
        "fee_types": "; ".join(row.fee_types),
    }


def write_custas_csv(*, result: CustasScanResult, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_CSV_FIELDS))
        writer.writeheader()
        for record in result.records:
            writer.writerow(_record_to_dict(record))


def write_custas_scan_json(*, result: CustasScanResult, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "consumers_scanned": result.consumers_scanned,
        "pdfs_seen": result.pdfs_seen,
        "pdfs_analyzed": result.pdfs_analyzed,
        "pdfs_skipped_path": result.pdfs_skipped_path,
        "court_fee_records": len(result.records),
        "records": [_record_to_dict(record) for record in result.records],
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_custas_process_csv(*, result: CustasScanResult, destination: Path) -> None:
    rows = build_custas_process_rows(records=result.records)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_PROCESS_CSV_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow(_process_row_to_dict(row))
