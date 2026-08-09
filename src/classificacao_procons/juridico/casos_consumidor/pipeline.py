"""Pipeline de varredura temática dos casos."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from classificacao_procons.gemini.client import get_api_key_from_env
from classificacao_procons.juridico.casos_consumidor.deposits_loader import (
    load_deposits_by_consumer,
)
from classificacao_procons.juridico.casos_consumidor.material import build_consumer_context
from classificacao_procons.juridico.casos_consumidor.models import (
    CasosScanResult,
    ConsumerCaseInsight,
)
from classificacao_procons.juridico.casos_consumidor.sentence import (
    extract_condemnation_amount_from_sentence,
)
from classificacao_procons.juridico.casos_consumidor.themes import (
    ThemeClassificationError,
    classify_theme_from_text,
    classify_theme_with_gemini,
)
from classificacao_procons.juridico.constants import DEFAULT_CONSUMER_PROCESSES_DRIVE_FOLDER_ID
from classificacao_procons.juridico.depositos.drive_crawl import list_consumer_folders


@dataclass(frozen=True)
class CasosScanOptions:
    root_folder_id: str = DEFAULT_CONSUMER_PROCESSES_DRIVE_FOLDER_ID
    work_dir: Path = Path("data/casos-scan-cache")
    token_path: str | None = None
    max_consumers: int | None = None
    deposits_json_path: Path = Path("data/depositos-judiciais.json")
    use_gemini: bool = True
    max_gemini_calls: int = 250


def _classify_theme(
    *,
    text: str,
    consumer_folder: str,
    gemini_api_key: str | None,
    use_gemini: bool,
    gemini_calls: list[int],
    max_gemini_calls: int,
) -> tuple:
    rules_primary, rules_secondary, rules_conf = classify_theme_from_text(text)
    if not use_gemini or not gemini_api_key or gemini_calls[0] >= max_gemini_calls:
        excerpt = text[:240].replace("\n", " ").strip() if text else None
        return rules_primary, rules_secondary, rules_conf, excerpt

    if rules_conf == "high" and rules_primary.value != "outros":
        excerpt = text[:240].replace("\n", " ").strip() if text else None
        return rules_primary, rules_secondary, rules_conf, excerpt

    try:
        gemini_calls[0] += 1
        return classify_theme_with_gemini(
            text=text or consumer_folder,
            consumer_folder=consumer_folder,
            api_key=gemini_api_key,
        )
    except ThemeClassificationError:
        excerpt = text[:240].replace("\n", " ").strip() if text else None
        return rules_primary, rules_secondary, rules_conf, excerpt


def scan_consumer_cases(options: CasosScanOptions) -> CasosScanResult:
    options.work_dir.mkdir(parents=True, exist_ok=True)
    gemini_api_key = get_api_key_from_env() if options.use_gemini else None
    gemini_calls = [0]
    deposits_by_consumer = load_deposits_by_consumer(options.deposits_json_path)

    consumers = list_consumer_folders(
        root_folder_id=options.root_folder_id,
        token_path=options.token_path,
        max_consumers=options.max_consumers,
    )

    cases: list[ConsumerCaseInsight] = []
    with_deposits = 0

    for index, consumer in enumerate(consumers, start=1):
        print(
            f"[casos-scan] {index}/{len(consumers)} {consumer.name}",
            file=sys.stderr,
            flush=True,
        )
        deposit_summary = deposits_by_consumer.get(consumer.name)
        if deposit_summary and deposit_summary.total_brl > 0:
            with_deposits += 1

        context = build_consumer_context(
            consumer_name=consumer.name,
            folder_id=consumer.file_id,
            work_dir=options.work_dir,
            token_path=options.token_path,
            deposit_summary=deposit_summary,
            gemini_api_key=gemini_api_key,
        )

        combined_text = "\n".join(
            part for part in (context.complaint_text, context.sentence_text) if part
        )
        primary, secondary, confidence, evidence = _classify_theme(
            text=combined_text or consumer.name,
            consumer_folder=consumer.name,
            gemini_api_key=gemini_api_key,
            use_gemini=options.use_gemini,
            gemini_calls=gemini_calls,
            max_gemini_calls=options.max_gemini_calls,
        )

        condemnation = extract_condemnation_amount_from_sentence(context.sentence_text)
        total_deposits = deposit_summary.total_brl if deposit_summary else None
        if total_deposits is not None and total_deposits <= 0:
            total_deposits = None

        process_numbers = context.process_numbers
        if deposit_summary and deposit_summary.process_numbers:
            merged = set(process_numbers) | set(deposit_summary.process_numbers)
            process_numbers = tuple(sorted(merged))

        cases.append(
            ConsumerCaseInsight(
                consumer_folder=consumer.name,
                process_numbers=process_numbers,
                primary_theme=primary,
                secondary_themes=secondary,
                theme_confidence=confidence,
                theme_evidence=evidence,
                total_judicial_deposits_brl=total_deposits,
                deposit_records_count=deposit_summary.record_count if deposit_summary else 0,
                condemnation_amount_brl=condemnation,
                has_sentence_pdf=context.has_sentence_pdf,
                complaint_excerpt=(
                    context.complaint_text[:300].replace("\n", " ").strip()
                    if context.complaint_text
                    else None
                ),
            ),
        )

    return CasosScanResult(
        cases=cases,
        consumers_scanned=len(consumers),
        consumers_with_deposits=with_deposits,
    )
