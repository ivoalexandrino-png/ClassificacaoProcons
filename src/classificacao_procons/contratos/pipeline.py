"""Pipeline Fase 1: documento assinado → Drive + Monday."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from classificacao_procons.contratos.autentique.client import (
    AutentiqueClientError,
    AutentiqueDocument,
    download_file,
    fetch_document,
)
from classificacao_procons.contratos.autentique.webhook import AutentiqueWebhookEvent
from classificacao_procons.contratos.drive_routing import (
    build_contract_pdf_filename,
    resolve_drive_destination,
)
from classificacao_procons.contratos.gemini_extractor import (
    ContractExtractionError,
    ContractMetadata,
    extract_contract_metadata,
)
from classificacao_procons.contratos.monday_contracts import (
    find_controle_item,
    register_contrato_item,
    update_controle_assinado,
)
from classificacao_procons.drive.client import DriveClientError, upload_pdf_to_folder_path
from classificacao_procons.monday.client import get_api_token_from_env

DEFAULT_DOWNLOAD_DIR = Path("downloads/contratos")
DEFAULT_STATE_PATH = Path("data/processed-contract-documents.json")


class ContractPipelineError(RuntimeError):
    """Erro no pipeline de contratos assinados."""


@dataclass(frozen=True)
class ContractPipelineOptions:
    download_dir: Path = DEFAULT_DOWNLOAD_DIR
    state_path: Path = DEFAULT_STATE_PATH
    token_path: str = "credentials/gmail-token.json"
    monday_api_token: str | None = None
    autentique_api_token: str | None = None
    gemini_api_key: str | None = None
    dry_run: bool = False
    skip_gemini: bool = False


@dataclass(frozen=True)
class ContractPipelineResult:
    document_id: str
    document_name: str
    drive_pdf_url: str | None
    controle_item_id: str | None
    contratos_item_id: str | None
    contratos_item_url: str | None
    skipped_duplicate: bool = False


def _load_processed_documents(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    documents = data.get("document_ids", [])
    return {str(item) for item in documents}


def _save_processed_documents(state_path: Path, document_ids: set[str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"document_ids": sorted(document_ids)}
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fallback_metadata(document_name: str) -> ContractMetadata:
    return ContractMetadata(
        counterparty_name=document_name,
        counterparty_cnpj=None,
        contract_type=None,
        company=None,
        start_date=None,
        end_date=None,
        property_name=None,
        summary=None,
    )


def process_finished_document(
    *,
    document_id: str,
    document_name: str | None = None,
    signed_pdf_url: str | None = None,
    options: ContractPipelineOptions | None = None,
) -> ContractPipelineResult:
    """Processa contrato assinado: Drive + Monday."""
    opts = options or ContractPipelineOptions()
    processed = _load_processed_documents(opts.state_path)
    if document_id in processed:
        return ContractPipelineResult(
            document_id=document_id,
            document_name=document_name or document_id,
            drive_pdf_url=None,
            controle_item_id=None,
            contratos_item_id=None,
            contratos_item_url=None,
            skipped_duplicate=True,
        )

    monday_token = opts.monday_api_token or get_api_token_from_env()
    if not monday_token and not opts.dry_run:
        raise ContractPipelineError("MONDAY_API_TOKEN não configurada.")

    document = _resolve_document(
        document_id=document_id,
        document_name=document_name,
        signed_pdf_url=signed_pdf_url,
        api_token=opts.autentique_api_token,
    )

    if opts.dry_run:
        return ContractPipelineResult(
            document_id=document.document_id,
            document_name=document.name,
            drive_pdf_url=document.signed_pdf_url,
            controle_item_id=None,
            contratos_item_id=None,
            contratos_item_url=None,
        )

    pdf_url = document.signed_pdf_url
    if not pdf_url:
        raise ContractPipelineError("URL do PDF assinado não disponível.")

    opts.download_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = opts.download_dir / f"{document.document_id}.pdf"
    try:
        download_file(url=pdf_url, destination=pdf_path)
    except AutentiqueClientError as exc:
        raise ContractPipelineError(str(exc)) from exc

    metadata = _extract_metadata(
        pdf_path=pdf_path,
        document_name=document.name,
        gemini_api_key=opts.gemini_api_key,
        skip_gemini=opts.skip_gemini,
    )

    destination = resolve_drive_destination(
        document_name=document.name,
        counterparty_name=metadata.counterparty_name,
        contract_type=metadata.contract_type,
        property_name=metadata.property_name,
    )

    try:
        _, _, drive_pdf_url = upload_pdf_to_folder_path(
            root_folder_id=destination.root_folder_id,
            path_parts=destination.path_parts,
            pdf_path=pdf_path,
            file_name=build_contract_pdf_filename(document_name=document.name),
            token_path=opts.token_path,
        )
    except DriveClientError as exc:
        raise ContractPipelineError(str(exc)) from exc

    controle_item = None
    if monday_token:
        controle_item = find_controle_item(
            api_token=monday_token,
            document_id=document.document_id,
            document_name=document.name,
        )

    tipo_label = controle_item.tipo if controle_item else None
    if monday_token and controle_item and controle_item.status != "Assinado":
        update_controle_assinado(
            api_token=monday_token,
            item_id=controle_item.item_id,
            signed_pdf_url=drive_pdf_url,
            signed_at=date.today(),
        )

    contratos_result = None
    if monday_token:
        contratos_result = register_contrato_item(
            api_token=monday_token,
            metadata=metadata,
            document_name=document.name,
            signed_pdf_url=drive_pdf_url,
            tipo_label=tipo_label,
        )

    processed.add(document.document_id)
    _save_processed_documents(opts.state_path, processed)

    return ContractPipelineResult(
        document_id=document.document_id,
        document_name=document.name,
        drive_pdf_url=drive_pdf_url,
        controle_item_id=controle_item.item_id if controle_item else None,
        contratos_item_id=contratos_result.contratos_item_id if contratos_result else None,
        contratos_item_url=contratos_result.contratos_item_url if contratos_result else None,
    )


def process_finished_webhook_event(
    event: AutentiqueWebhookEvent,
    *,
    options: ContractPipelineOptions | None = None,
) -> ContractPipelineResult:
    """Processa evento document.finished do Autentique."""
    if event.event_type != "document.finished":
        raise ContractPipelineError(f"Evento não suportado: {event.event_type}")

    return process_finished_document(
        document_id=event.document_id,
        document_name=event.document_name,
        signed_pdf_url=event.signed_pdf_url,
        options=options,
    )


def _resolve_document(
    *,
    document_id: str,
    document_name: str | None,
    signed_pdf_url: str | None,
    api_token: str | None,
) -> AutentiqueDocument:
    if document_name and signed_pdf_url:
        return AutentiqueDocument(
            document_id=document_id,
            name=document_name,
            signed_pdf_url=signed_pdf_url,
            original_pdf_url=None,
        )
    try:
        return fetch_document(document_id=document_id, api_token=api_token)
    except AutentiqueClientError as exc:
        raise ContractPipelineError(str(exc)) from exc


def _extract_metadata(
    *,
    pdf_path: Path,
    document_name: str,
    gemini_api_key: str | None,
    skip_gemini: bool,
) -> ContractMetadata:
    if skip_gemini:
        return _fallback_metadata(document_name)

    try:
        return extract_contract_metadata(
            pdf_path=pdf_path,
            document_name=document_name,
            api_key=gemini_api_key,
        )
    except ContractExtractionError:
        return _fallback_metadata(document_name)
