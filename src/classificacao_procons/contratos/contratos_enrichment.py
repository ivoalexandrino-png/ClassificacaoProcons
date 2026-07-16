"""Processamento de itens criados no quadro Contratos via automação Monday."""

from __future__ import annotations

from pathlib import Path

from classificacao_procons.contratos.gemini_extractor import (
    ContractExtractionError,
    ContractMetadata,
    extract_contract_metadata,
)
from classificacao_procons.contratos.monday_contracts import (
    enrich_contratos_item_columns,
    fetch_contratos_item_name,
)
from classificacao_procons.contratos.monday_webhook import MondayWebhookEvent
from classificacao_procons.monday.client import MondayClientError


class ContratosEnrichmentError(RuntimeError):
    """Erro ao enriquecer item do quadro Contratos."""


def process_contratos_item_created(
    event: MondayWebhookEvent,
    *,
    api_token: str,
    gemini_api_key: str | None = None,
    skip_gemini: bool = False,
    pdf_path: Path | None = None,
) -> None:
    """Preenche colunas de item recém-criado no quadro Contratos."""
    if not event.item_id:
        raise ContratosEnrichmentError("Item ID ausente no evento Monday.")

    try:
        item_name = fetch_contratos_item_name(api_token=api_token, item_id=event.item_id)
    except MondayClientError as exc:
        raise ContratosEnrichmentError(str(exc)) from exc

    metadata = _resolve_metadata(
        document_name=item_name,
        pdf_path=pdf_path,
        gemini_api_key=gemini_api_key,
        skip_gemini=skip_gemini,
    )

    try:
        enrich_contratos_item_columns(
            api_token=api_token,
            item_id=event.item_id,
            metadata=metadata,
            document_name=item_name,
            pdf_path=pdf_path,
        )
    except MondayClientError as exc:
        raise ContratosEnrichmentError(str(exc)) from exc


def _resolve_metadata(
    *,
    document_name: str,
    pdf_path: Path | None,
    gemini_api_key: str | None,
    skip_gemini: bool,
) -> ContractMetadata:
    if skip_gemini or pdf_path is None:
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
    try:
        return extract_contract_metadata(
            pdf_path=pdf_path,
            document_name=document_name,
            api_key=gemini_api_key,
        )
    except ContractExtractionError:
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
