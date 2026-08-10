"""Deduplicação de guia + comprovante do mesmo pagamento de custas."""

from __future__ import annotations

from classificacao_procons.juridico.custas.models import CourtFeeRecord, ExtractionConfidence
from classificacao_procons.juridico.custas.path_rules import custas_document_priority

_CONFIDENCE_RANK = {
    ExtractionConfidence.LOW: 0,
    ExtractionConfidence.MEDIUM: 1,
    ExtractionConfidence.HIGH: 2,
}


def _record_key(record: CourtFeeRecord) -> tuple[str, str, str]:
    amount = f"{record.amount_brl:.2f}" if record.amount_brl is not None else ""
    date = record.payment_date or ""
    process_number = record.process_number or ""
    if amount or date or process_number:
        return (record.consumer_folder, amount, date or process_number)
    return (record.consumer_folder, record.drive_file_id, "")


def _record_score(record: CourtFeeRecord) -> tuple[int, int, int]:
    path = record.drive_path
    file_name = path.rsplit("/", 1)[-1]
    return (
        _CONFIDENCE_RANK.get(record.confidence, 0),
        1 if record.amount_brl is not None else 0,
        custas_document_priority(drive_path=path, file_name=file_name),
    )


def dedupe_court_fee_records(records: list[CourtFeeRecord]) -> list[CourtFeeRecord]:
    best_by_key: dict[tuple[str, str, str], CourtFeeRecord] = {}
    for record in records:
        key = _record_key(record)
        existing = best_by_key.get(key)
        if existing is None or _record_score(record) > _record_score(existing):
            best_by_key[key] = record
    return sorted(
        best_by_key.values(),
        key=lambda item: (item.consumer_folder.casefold(), item.drive_path.casefold()),
    )
