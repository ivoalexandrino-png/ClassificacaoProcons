"""Pipeline de varredura de custas processuais no Drive."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from classificacao_procons.drive.client import DriveClientError
from classificacao_procons.drive.reader import download_drive_file
from classificacao_procons.gemini.client import get_api_key_from_env
from classificacao_procons.juridico.custas.classify import (
    has_strong_custas_signal,
    infer_fee_type,
    is_court_fees_document,
)
from classificacao_procons.juridico.custas.dedupe import dedupe_court_fee_records
from classificacao_procons.juridico.custas.fields import extract_custas_amount_brl
from classificacao_procons.juridico.custas.gemini_custas import (
    CustasGeminiError,
    analyze_custas_pdf_with_gemini,
)
from classificacao_procons.juridico.custas.models import (
    CourtFeeRecord,
    CustasScanResult,
    ExtractionConfidence,
)
from classificacao_procons.juridico.custas.path_rules import (
    path_suggests_court_fees,
    should_analyze_pdf,
)
from classificacao_procons.juridico.depositos.classify import classify_document_text
from classificacao_procons.juridico.depositos.drive_crawl import (
    DrivePdfItem,
    list_consumer_folders,
    walk_pdfs_under_folder,
)
from classificacao_procons.juridico.depositos.fields import (
    extract_payment_date,
    extract_process_number,
)
from classificacao_procons.juridico.depositos.models import DocumentKind
from classificacao_procons.juridico.depositos.path_rules import path_suggests_deposit_workflow
from classificacao_procons.juridico.depositos.text_extract import extract_pdf_text


@dataclass(frozen=True)
class CustasScanOptions:
    root_folder_id: str
    work_dir: Path
    token_path: str | None = None
    max_consumers: int | None = 30
    use_gemini: bool = True
    max_gemini_calls: int = 600
    allow_vision: bool = True


def _safe_local_name(file_name: str) -> str:
    cleaned = re.sub(r"[^\w.\- ()]", "_", file_name).strip()
    return cleaned or "documento"


def _confidence_for_rules(
    *,
    is_fees: bool,
    amount,
    process_number: str | None,
) -> ExtractionConfidence:
    if not is_fees:
        return ExtractionConfidence.LOW
    if amount is not None and process_number:
        return ExtractionConfidence.HIGH
    if amount is not None or process_number:
        return ExtractionConfidence.MEDIUM
    return ExtractionConfidence.LOW


def _is_custas_candidate(*, kind: DocumentKind, text: str, drive_path: str) -> bool:
    if kind == DocumentKind.JUDICIAL_DEPOSIT:
        return False
    if kind == DocumentKind.IRRELEVANT:
        return False
    if kind == DocumentKind.COURT_FEES:
        return True
    if is_court_fees_document(text):
        return True
    if path_suggests_court_fees(drive_path) and kind != DocumentKind.JUDICIAL_DEPOSIT:
        if path_suggests_deposit_workflow(drive_path) and not path_suggests_court_fees(drive_path):
            return False
        return True
    return False


def _needs_gemini(
    *,
    is_fees: bool,
    drive_path: str,
    text: str,
    amount,
    process_number: str | None,
) -> bool:
    if not path_suggests_court_fees(drive_path) and not has_strong_custas_signal(text):
        return False
    if classify_document_text(text) == DocumentKind.JUDICIAL_DEPOSIT:
        return False
    if is_fees and amount is not None and process_number:
        return False
    if is_fees:
        return amount is None or process_number is None
    return True


def _analyze_pdf_item(
    *,
    consumer_folder: str,
    item: DrivePdfItem,
    options: CustasScanOptions,
    gemini_api_key: str | None,
    gemini_calls: list[int],
) -> CourtFeeRecord | None:
    local_path = options.work_dir / consumer_folder / _safe_local_name(item.name)
    try:
        download_drive_file(
            file_id=item.file_id,
            destination=local_path,
            token_path=options.token_path,
        )
    except DriveClientError:
        return None

    extracted = extract_pdf_text(
        local_path,
        gemini_api_key=gemini_api_key if options.allow_vision else None,
        allow_vision=options.allow_vision and path_suggests_court_fees(item.drive_path),
    )
    text = extracted.text
    kind = classify_document_text(text)
    is_fees = _is_custas_candidate(kind=kind, text=text, drive_path=item.drive_path)

    amount_extraction = extract_custas_amount_brl(text)
    amount = amount_extraction.amount_brl
    reference_base_brl = amount_extraction.reference_base_brl
    process_number = extract_process_number(text)
    payment_date = extract_payment_date(text)
    fee_type = infer_fee_type(text=text, drive_path=item.drive_path)
    method = (
        f"{extracted.method}+{amount_extraction.method}"
        if amount_extraction.method != "custas_none"
        else extracted.method
    )
    confidence = _confidence_for_rules(
        is_fees=is_fees,
        amount=amount,
        process_number=process_number,
    )
    notes: str | None = None

    use_gemini = (
        options.use_gemini
        and gemini_api_key
        and gemini_calls[0] < options.max_gemini_calls
        and _needs_gemini(
            is_fees=is_fees,
            drive_path=item.drive_path,
            text=text,
            amount=amount,
            process_number=process_number,
        )
    )
    if use_gemini:
        try:
            gemini_calls[0] += 1
            analysis = analyze_custas_pdf_with_gemini(
                pdf_path=local_path,
                drive_path=item.drive_path,
                api_key=gemini_api_key,
            )
            is_fees = analysis.is_court_fees
            if analysis.process_number:
                process_number = analysis.process_number
            if analysis.amount_brl is not None:
                amount = analysis.amount_brl
            if analysis.payment_date:
                payment_date = analysis.payment_date
            fee_type = analysis.fee_type
            notes = analysis.notes
            method = f"{method}+gemini"
            if is_fees:
                confidence = ExtractionConfidence.MEDIUM
        except CustasGeminiError as exc:
            notes = f"gemini_error: {exc}"

    if not is_fees:
        return None

    if (
        amount is None
        and process_number is None
        and not has_strong_custas_signal(text)
        and "+gemini" not in method
    ):
        return None

    return CourtFeeRecord(
        consumer_folder=consumer_folder,
        drive_file_id=item.file_id,
        drive_path=item.drive_path,
        drive_url=item.web_view_link,
        process_number=process_number,
        amount_brl=amount,
        payment_date=payment_date,
        fee_type=fee_type,
        extraction_method=method,
        confidence=confidence,
        notes=notes,
        reference_base_brl=reference_base_brl,
    )


def scan_court_fees(options: CustasScanOptions) -> CustasScanResult:
    options.work_dir.mkdir(parents=True, exist_ok=True)
    gemini_api_key = get_api_key_from_env() if options.use_gemini else None
    gemini_calls = [0]

    consumers = list_consumer_folders(
        root_folder_id=options.root_folder_id,
        token_path=options.token_path,
        max_consumers=options.max_consumers,
    )

    result = CustasScanResult(consumers_scanned=len(consumers))

    for index, consumer in enumerate(consumers, start=1):
        print(
            f"[custas-scan] {index}/{len(consumers)} {consumer.name}",
            file=sys.stderr,
            flush=True,
        )
        pdfs = walk_pdfs_under_folder(
            folder_id=consumer.file_id,
            path_prefix=consumer.name,
            token_path=options.token_path,
        )
        result.pdfs_seen += len(pdfs)
        for item in pdfs:
            if not should_analyze_pdf(drive_path=item.drive_path, file_name=item.name):
                result.pdfs_skipped_path += 1
                continue
            result.pdfs_analyzed += 1
            record = _analyze_pdf_item(
                consumer_folder=consumer.name,
                item=item,
                options=options,
                gemini_api_key=gemini_api_key,
                gemini_calls=gemini_calls,
            )
            if record is not None:
                result.records.append(record)

    result.records = dedupe_court_fee_records(result.records)
    return result
