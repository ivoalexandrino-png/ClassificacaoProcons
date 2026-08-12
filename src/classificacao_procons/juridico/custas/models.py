"""Modelos para relatório de custas processuais."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class CourtFeeType(StrEnum):
    INITIAL = "initial"
    FINAL = "final"
    APPEAL = "appeal"
    PREPARO = "preparo"
    INTIMATION = "intimation"
    OTHER = "other"


class ExtractionConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class CourtFeeRecord:
    consumer_folder: str
    drive_file_id: str
    drive_path: str
    drive_url: str | None
    process_number: str | None
    amount_brl: Decimal | None
    payment_date: str | None
    fee_type: CourtFeeType
    extraction_method: str
    confidence: ExtractionConfidence
    notes: str | None = None


@dataclass
class CustasScanResult:
    records: list[CourtFeeRecord] = field(default_factory=list)
    pdfs_seen: int = 0
    pdfs_analyzed: int = 0
    pdfs_skipped_path: int = 0
    consumers_scanned: int = 0
