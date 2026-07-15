"""Pipeline de elaboração de resposta ao Procon."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from classificacao_procons.drive.client import DriveClientError
from classificacao_procons.drive.reader import (
    download_drive_file,
    ensure_output_folder,
    resolve_sac_folder_context,
    upload_text_file,
)
from classificacao_procons.gemini import (
    GeminiClientError,
    generate_procon_response,
    get_api_key_from_env,
)
from classificacao_procons.google_auth import has_valid_token
from classificacao_procons.models import ElaboratedResponseResult, MondayCaseReady
from classificacao_procons.monday.cases import list_cases_ready_for_elaboration
from classificacao_procons.monday.client import MondayClientError, get_api_token_from_env

DEFAULT_WORK_DIR = Path("downloads/elaboration")
DEFAULT_STATE_PATH = Path("data/elaborated-responses.json")


class ResponsePipelineError(RuntimeError):
    """Erro geral na elaboração de respostas."""


@dataclass(frozen=True)
class ResponsePipelineOptions:
    work_dir: Path = DEFAULT_WORK_DIR
    state_path: Path = DEFAULT_STATE_PATH
    token_path: str = "credentials/gmail-token.json"
    monday_api_token: str | None = None
    gemini_api_key: str | None = None
    max_cases: int = 20
    dry_run: bool = False


def _load_elaborated_item_ids(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    item_ids = data.get("monday_item_ids", [])
    return {str(item_id) for item_id in item_ids}


def _save_elaborated_item_ids(state_path: Path, item_ids: set[str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"monday_item_ids": sorted(item_ids)}
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_monday_token(options: ResponsePipelineOptions) -> str | None:
    return options.monday_api_token or get_api_token_from_env()


def _resolve_gemini_key(options: ResponsePipelineOptions) -> str | None:
    return options.gemini_api_key or get_api_key_from_env()


def _elaborate_case(
    case: MondayCaseReady,
    *,
    options: ResponsePipelineOptions,
    elaborated_item_ids: set[str],
) -> ElaboratedResponseResult:
    if case.item_id in elaborated_item_ids:
        return ElaboratedResponseResult(
            status="skipped_duplicate",
            monday_item_id=case.item_id,
            consumer_name=case.item_name,
            protocol_number=case.protocol_number,
            error="Resposta já elaborada anteriormente.",
        )

    if options.dry_run:
        return ElaboratedResponseResult(
            status="dry_run",
            monday_item_id=case.item_id,
            consumer_name=case.item_name,
            protocol_number=case.protocol_number,
        )

    try:
        sac_context = resolve_sac_folder_context(
            docs_sac_url=case.docs_sac_url,
            token_path=options.token_path,
        )
    except DriveClientError as exc:
        return ElaboratedResponseResult(
            status="error",
            monday_item_id=case.item_id,
            consumer_name=case.item_name,
            protocol_number=case.protocol_number,
            error=str(exc),
        )

    case_dir = options.work_dir / case.item_id
    complaint_pdf_path = case_dir / "reclamacao-original.pdf"
    try:
        download_drive_file(
            file_id=sac_context.complaint_pdf.file_id,
            destination=complaint_pdf_path,
            token_path=options.token_path,
        )
    except DriveClientError as exc:
        return ElaboratedResponseResult(
            status="error",
            monday_item_id=case.item_id,
            consumer_name=case.item_name,
            protocol_number=case.protocol_number,
            error=str(exc),
        )

    sac_summary = ""
    if sac_context.summary_txt is not None:
        summary_path = case_dir / sac_context.summary_txt.name
        try:
            download_drive_file(
                file_id=sac_context.summary_txt.file_id,
                destination=summary_path,
                token_path=options.token_path,
            )
            sac_summary = summary_path.read_text(encoding="utf-8", errors="replace").strip()
        except (DriveClientError, OSError) as exc:
            return ElaboratedResponseResult(
                status="error",
                monday_item_id=case.item_id,
                consumer_name=case.item_name,
                protocol_number=case.protocol_number,
                error=f"Falha ao ler resumo TXT do SAC: {exc}",
            )

    if not sac_summary:
        return ElaboratedResponseResult(
            status="error",
            monday_item_id=case.item_id,
            consumer_name=case.item_name,
            protocol_number=case.protocol_number,
            error="Resumo TXT do SAC não encontrado na pasta.",
        )

    gemini_key = _resolve_gemini_key(options)
    if not gemini_key:
        return ElaboratedResponseResult(
            status="error",
            monday_item_id=case.item_id,
            consumer_name=case.item_name,
            protocol_number=case.protocol_number,
            error="GEMINI_API_KEY não configurada.",
        )

    try:
        generated = generate_procon_response(
            complaint_pdf_path=complaint_pdf_path,
            sac_summary=sac_summary,
            supporting_file_names=[file_info.name for file_info in sac_context.supporting_files],
            consumer_name=case.item_name,
            protocol_number=case.protocol_number or case.item_id,
            api_key=gemini_key,
        )
    except GeminiClientError as exc:
        return ElaboratedResponseResult(
            status="error",
            monday_item_id=case.item_id,
            consumer_name=case.item_name,
            protocol_number=case.protocol_number,
            error=str(exc),
        )

    try:
        output_folder_id = ensure_output_folder(
            parent_folder_id=sac_context.consumer_folder_id,
            token_path=options.token_path,
        )
        analysis_url = upload_text_file(
            folder_id=output_folder_id,
            file_name="resposta-analise.txt",
            content=generated.analysis,
            token_path=options.token_path,
        )
        full_url = upload_text_file(
            folder_id=output_folder_id,
            file_name="resposta-completa.txt",
            content=generated.final_response,
            token_path=options.token_path,
        )
        summary_url = upload_text_file(
            folder_id=output_folder_id,
            file_name="resposta-resumo-1024.txt",
            content=generated.portal_summary,
            token_path=options.token_path,
        )
    except DriveClientError as exc:
        return ElaboratedResponseResult(
            status="error",
            monday_item_id=case.item_id,
            consumer_name=case.item_name,
            protocol_number=case.protocol_number,
            error=str(exc),
        )

    elaborated_item_ids.add(case.item_id)
    _save_elaborated_item_ids(options.state_path, elaborated_item_ids)

    return ElaboratedResponseResult(
        status="success",
        monday_item_id=case.item_id,
        consumer_name=case.item_name,
        protocol_number=case.protocol_number,
        analysis_file_url=analysis_url,
        full_response_file_url=full_url,
        summary_response_file_url=summary_url,
    )


def elaborate_pending_responses(
    options: ResponsePipelineOptions | None = None,
) -> list[ElaboratedResponseResult]:
    """Elabora respostas para casos com Docs SAC preenchido no Monday."""
    options = options or ResponsePipelineOptions()

    if not options.dry_run and not has_valid_token(options.token_path):
        raise ResponsePipelineError("Google não conectado. Rode: procon-email auth")

    monday_token = _resolve_monday_token(options)
    if not monday_token and not options.dry_run:
        raise ResponsePipelineError("MONDAY_API_TOKEN não configurada.")

    try:
        cases = list_cases_ready_for_elaboration(
            api_token=monday_token,
            limit=options.max_cases,
        )
    except MondayClientError as exc:
        raise ResponsePipelineError(str(exc)) from exc

    elaborated_item_ids = _load_elaborated_item_ids(options.state_path)
    results: list[ElaboratedResponseResult] = []

    for case in cases:
        results.append(
            _elaborate_case(
                case,
                options=options,
                elaborated_item_ids=elaborated_item_ids,
            ),
        )

    return results
