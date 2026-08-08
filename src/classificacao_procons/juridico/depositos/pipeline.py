"""Pipeline de varredura de depósitos judiciais no Drive."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from classificacao_procons.drive.client import DriveClientError
from classificacao_procons.drive.reader import download_drive_file
from classificacao_procons.gemini.client import get_api_key_from_env
from classificacao_procons.juridico.depositos.classify import (
    classify_document_text,
    infer_deposit_purpose,
)
from classificacao_procons.juridico.depositos.drive_crawl import (
    DrivePdfItem,
    list_consumer_folders,
    walk_pdfs_under_folder,
)
from classificacao_procons.juridico.depositos.fields import (
    extract_amount_brl,
    extract_payment_date,
    extract_process_number,
)
from classificacao_procons.juridico.depositos.gemini_deposit import (
    DepositGeminiError,
    analyze_deposit_pdf_with_gemini,
)
from classificacao_procons.juridico.depositos.models import (
    DepositScanResult,
    DocumentKind,
    ExtractionConfidence,
    JudicialDepositRecord,
)
from classificacao_procons.juridico.depositos.path_rules import (
    path_suggests_court_fees,
    path_suggests_deposit_workflow,
    should_analyze_pdf,
)
from classificacao_procons.juridico.depositos.text_extract import extract_pdf_text


@dataclass(frozen=True)
class DepositScanOptions:
    root_folder_id: str
    work_dir: Path
    token_path: str | None = None
    max_consumers: int | None = 30
    use_gemini: bool = True
    max_gemini_calls: int = 80
    allow_vision: bool = True


def _safe_local_name(file_name: str) -> str:
    cleaned = re.sub(r"[^\w.\- ()]", "_", file_name).strip()
    return cleaned or "documento"


def _confidence_for_rules(
    *,
    kind: DocumentKind,
    amount,
    process_number: str | None,
) -> ExtractionConfidence:
    if kind != DocumentKind.JUDICIAL_DEPOSIT:
        return ExtractionConfidence.LOW
    if amount is not None and process_number:
        return ExtractionConfidence.HIGH
    if amount is not None or process_number:
        return ExtractionConfidence.MEDIUM
    return ExtractionConfidence.LOW


def _needs_gemini(
    *,
    kind: DocumentKind,
    drive_path: str,
    text: str,
    amount,
    process_number: str | None,
) -> bool:
    if kind == DocumentKind.COURT_FEES or kind == DocumentKind.IRRELEVANT:
        return False
    if kind == DocumentKind.JUDICIAL_DEPOSIT and amount is not None:
        return False
    if path_suggests_court_fees(drive_path):
        return False
    if kind == DocumentKind.JUDICIAL_DEPOSIT:
        return amount is None or process_number is None
    if not path_suggests_deposit_workflow(drive_path):
        return False
    normalized = text.casefold()
    if kind == DocumentKind.UNKNOWN and not normalized.strip():
        return True
    deposit_hints = (
        "deposito",
        "depósito",
        "judicial",
        "conta judicial",
        "codigo de barras",
        "condenacao",
        "condenação",
    )
    return any(hint in normalized for hint in deposit_hints)


def _analyze_pdf_item(
    *,
    consumer_folder: str,
    item: DrivePdfItem,
    options: DepositScanOptions,
    gemini_api_key: str | None,
    gemini_calls: list[int],
) -> JudicialDepositRecord | None:
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
        allow_vision=options.allow_vision
        and (
            path_suggests_deposit_workflow(item.drive_path)
            or path_suggests_court_fees(item.drive_path)
        ),
    )
    text = extracted.text
    kind = classify_document_text(text)
    if path_suggests_court_fees(item.drive_path) and kind != DocumentKind.JUDICIAL_DEPOSIT:
        kind = DocumentKind.COURT_FEES

    amount = extract_amount_brl(text)
    process_number = extract_process_number(text)
    payment_date = extract_payment_date(text)
    purpose = infer_deposit_purpose(text=text, drive_path=item.drive_path)
    method = extracted.method
    confidence = _confidence_for_rules(kind=kind, amount=amount, process_number=process_number)
    notes: str | None = None

    use_gemini = (
        options.use_gemini
        and gemini_api_key
        and gemini_calls[0] < options.max_gemini_calls
        and _needs_gemini(
            kind=kind,
            drive_path=item.drive_path,
            text=text,
            amount=amount,
            process_number=process_number,
        )
    )
    if use_gemini:
        try:
            gemini_calls[0] += 1
            analysis = analyze_deposit_pdf_with_gemini(
                pdf_path=local_path,
                drive_path=item.drive_path,
                api_key=gemini_api_key,
            )
            kind = analysis.document_kind
            if analysis.process_number:
                process_number = analysis.process_number
            if analysis.amount_brl is not None:
                amount = analysis.amount_brl
            if analysis.payment_date:
                payment_date = analysis.payment_date
            purpose = analysis.deposit_purpose
            notes = analysis.notes
            method = f"{method}+gemini"
            if kind == DocumentKind.JUDICIAL_DEPOSIT:
                confidence = ExtractionConfidence.MEDIUM
        except DepositGeminiError as exc:
            notes = f"gemini_error: {exc}"

    if kind != DocumentKind.JUDICIAL_DEPOSIT:
        return None

    return JudicialDepositRecord(
        consumer_folder=consumer_folder,
        drive_file_id=item.file_id,
        drive_path=item.drive_path,
        drive_url=item.web_view_link,
        document_kind=kind,
        process_number=process_number,
        amount_brl=amount,
        payment_date=payment_date,
        deposit_purpose=purpose,
        extraction_method=method,
        confidence=confidence,
        notes=notes,
    )


def scan_consumer_deposits(options: DepositScanOptions) -> DepositScanResult:
    options.work_dir.mkdir(parents=True, exist_ok=True)
    gemini_api_key = get_api_key_from_env() if options.use_gemini else None
    gemini_calls = [0]

    consumers = list_consumer_folders(
        root_folder_id=options.root_folder_id,
        token_path=options.token_path,
        max_consumers=options.max_consumers,
    )

    result = DepositScanResult(consumers_scanned=len(consumers))

    for consumer in consumers:
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

    return result
