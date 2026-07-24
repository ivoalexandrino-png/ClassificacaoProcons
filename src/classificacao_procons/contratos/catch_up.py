"""Sincronização em lote Autentique → Monday/Drive (modo manual / Cloud Agent)."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass

from classificacao_procons.contratos.autentique.client import (
    AutentiqueClientError,
    AutentiqueDocumentSummary,
    list_documents,
)
from classificacao_procons.contratos.constants import CONTROLE_STATUS_ASSINADO
from classificacao_procons.contratos.controle_sync import (
    ControleSyncError,
    sync_controle_from_autentique,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import (
    build_controle_assinaturas_index,
    find_controle_item_by_autentique_id,
)
from classificacao_procons.contratos.pipeline import (
    ContractPipelineError,
    ContractPipelineOptions,
    ContractPipelineResult,
    process_finished_document,
)
from classificacao_procons.monday.client import get_api_token_from_env


class CatchUpError(RuntimeError):
    """Erro na sincronização em lote de contratos."""


@dataclass(frozen=True)
class CatchUpProcessItemResult:
    document_id: str
    document_name: str
    action: str
    detail: str | None = None
    contratos_item_id: str | None = None
    drive_pdf_url: str | None = None


@dataclass(frozen=True)
class CatchUpResult:
    sync_created: int
    sync_updated: int
    sync_failed: int
    signed_total: int
    processed: int
    skipped: int
    process_failed: int
    dry_run: bool
    items: tuple[CatchUpProcessItemResult, ...]


def catch_up_contratos(
    *,
    monday_api_token: str | None = None,
    autentique_api_token: str | None = None,
    dry_run: bool = False,
    max_pages: int = 50,
    skip_gemini: bool = False,
    token_path: str = "credentials/gmail-token.json",
    process_signed: bool = True,
) -> CatchUpResult:
    """Sincroniza Controle Assinaturas e processa contratos totalmente assinados."""
    monday_token = monday_api_token or get_api_token_from_env()
    if not monday_token:
        raise CatchUpError("MONDAY_API_TOKEN não configurada.")

    try:
        sync_result = sync_controle_from_autentique(
            monday_api_token=monday_token,
            autentique_api_token=autentique_api_token,
            dry_run=dry_run,
            max_pages=max_pages,
            update_existing=True,
        )
    except ControleSyncError as exc:
        raise CatchUpError(str(exc)) from exc

    if not process_signed:
        return CatchUpResult(
            sync_created=sync_result.created,
            sync_updated=sync_result.updated,
            sync_failed=sync_result.failed,
            signed_total=0,
            processed=0,
            skipped=0,
            process_failed=0,
            dry_run=dry_run,
            items=(),
        )

    try:
        documents = list_documents(api_token=autentique_api_token, max_pages=max_pages)
    except AutentiqueClientError as exc:
        raise CatchUpError(str(exc)) from exc

    signed_documents = [document for document in documents if document.is_fully_signed]
    index = build_controle_assinaturas_index(api_token=monday_token)
    pipeline_options = ContractPipelineOptions(
        dry_run=dry_run,
        skip_gemini=skip_gemini,
        token_path=token_path,
        monday_api_token=monday_token,
        autentique_api_token=autentique_api_token,
    )

    items: list[CatchUpProcessItemResult] = []
    processed = 0
    skipped = 0
    process_failed = 0

    for document in signed_documents:
        controle_item = index.get_item(document.document_id)
        if controle_item is None:
            controle_item = find_controle_item_by_autentique_id(
                api_token=monday_token,
                document_id=document.document_id,
            )

        skip_reason = _skip_signed_processing_reason(
            document=document,
            controle_item=controle_item,
        )
        if skip_reason:
            skipped += 1
            items.append(
                CatchUpProcessItemResult(
                    document_id=document.document_id,
                    document_name=document.name,
                    action="skipped",
                    detail=skip_reason,
                ),
            )
            continue

        if dry_run:
            processed += 1
            items.append(
                CatchUpProcessItemResult(
                    document_id=document.document_id,
                    document_name=document.name,
                    action="would_process",
                    detail=json.dumps(
                        {
                            "signed": True,
                            "controle_item_id": controle_item.item_id if controle_item else None,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            continue

        try:
            result = process_finished_document(
                document_id=document.document_id,
                document_name=document.name,
                signed_pdf_url=document.signed_pdf_url,
                options=pipeline_options,
            )
        except (ContractPipelineError, OSError, TimeoutError) as exc:
            process_failed += 1
            items.append(
                CatchUpProcessItemResult(
                    document_id=document.document_id,
                    document_name=document.name,
                    action="failed",
                    detail=str(exc),
                ),
            )
            continue
        except Exception as exc:
            process_failed += 1
            items.append(
                CatchUpProcessItemResult(
                    document_id=document.document_id,
                    document_name=document.name,
                    action="failed",
                    detail=f"{type(exc).__name__}: {exc}",
                ),
            )
            continue

        if result.skipped_duplicate:
            skipped += 1
            items.append(
                CatchUpProcessItemResult(
                    document_id=document.document_id,
                    document_name=document.name,
                    action="skipped",
                    detail="local_state_processed",
                ),
            )
            continue

        processed += 1
        items.append(_process_item_result(document=document, result=result))

    return CatchUpResult(
        sync_created=sync_result.created,
        sync_updated=sync_result.updated,
        sync_failed=sync_result.failed,
        signed_total=len(signed_documents),
        processed=processed,
        skipped=skipped,
        process_failed=process_failed,
        dry_run=dry_run,
        items=tuple(items),
    )


def _process_item_result(
    *,
    document: AutentiqueDocumentSummary,
    result: ContractPipelineResult,
) -> CatchUpProcessItemResult:
    return CatchUpProcessItemResult(
        document_id=document.document_id,
        document_name=document.name,
        action="processed",
        detail=json.dumps(
            {
                "drive_folder_path": result.drive_folder_path,
                "controle_item_id": result.controle_item_id,
                "contratos_registration_mode": result.contratos_registration_mode,
            },
            ensure_ascii=False,
        ),
        contratos_item_id=result.contratos_item_id,
        drive_pdf_url=result.drive_pdf_url,
    )


def _skip_signed_processing_reason(
    *,
    document: AutentiqueDocumentSummary,
    controle_item: ControleAssinaturasItem | None,
) -> str | None:
    if not document.is_fully_signed:
        return "not_fully_signed"
    if controle_item is None:
        return None
    if _status_matches(controle_item.status, CONTROLE_STATUS_ASSINADO):
        return "controle_already_assinado"
    return None


def _status_matches(current: str | None, expected: str) -> bool:
    if not current:
        return False
    normalized_current = unicodedata.normalize("NFKD", current).casefold().strip()
    normalized_expected = unicodedata.normalize("NFKD", expected).casefold().strip()
    return normalized_current == normalized_expected
