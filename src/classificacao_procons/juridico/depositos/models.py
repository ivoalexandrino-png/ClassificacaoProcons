"""Modelos para relatório de depósitos judiciais."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class DocumentKind(StrEnum):
    JUDICIAL_DEPOSIT = "judicial_deposit"
    COURT_FEES = "court_fees"
    IRRELEVANT = "irrelevant"
    UNKNOWN = "unknown"


class DepositPurpose(StrEnum):
    CONDEMNATION = "condemnation"
    AGREEMENT = "agreement"
    GUARANTEE = "guarantee"
    CONSUMER_REFUND = "consumer_refund"
    UNKNOWN = "unknown"


class ExtractionConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class JudicialDepositRecord:
    consumer_folder: str
    drive_file_id: str
    drive_path: str
    drive_url: str | None
    document_kind: DocumentKind
    process_number: str | None
    amount_brl: Decimal | None
    payment_date: str | None
    deposit_purpose: DepositPurpose
    extraction_method: str
    confidence: ExtractionConfidence
    notes: str | None = None


@dataclass
class DepositScanResult:
    records: list[JudicialDepositRecord] = field(default_factory=list)
    pdfs_seen: int = 0
    pdfs_analyzed: int = 0
    pdfs_skipped_path: int = 0
    consumers_scanned: int = 0
