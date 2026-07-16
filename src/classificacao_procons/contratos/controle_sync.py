"""Sincroniza documentos do Autentique com o quadro Controle Assinaturas."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime

from classificacao_procons.contratos.autentique.client import (
    AutentiqueClientError,
    AutentiqueDocumentSummary,
    create_signature_link,
    list_documents,
)
from classificacao_procons.contratos.constants import (
    CONTROLE_GROUP_ASSINADOS,
    CONTROLE_STATUS_AGUARDANDO_OUTROS,
    CONTROLE_STATUS_ASSINADO,
)
from classificacao_procons.contratos.contratos_routing import (
    is_supplemental_document,
)
from classificacao_procons.contratos.drive_routing import infer_category, infer_monday_tipo
from classificacao_procons.contratos.monday_contracts import (
    build_controle_assinaturas_index,
    create_controle_assinatura_item,
    load_controle_board_groups,
)
from classificacao_procons.monday.client import MondayClientError, get_api_token_from_env


class ControleSyncError(RuntimeError):
    """Erro ao sincronizar Controle Assinaturas."""


@dataclass(frozen=True)
class ControleSyncItemResult:
    document_id: str
    document_name: str
    action: str
    monday_item_id: str | None = None
    monday_item_url: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class ControleSyncResult:
    total_autentique: int
    already_in_monday: int
    created: int
    skipped: int
    failed: int
    dry_run: bool
    items: tuple[ControleSyncItemResult, ...]


def sync_controle_from_autentique(
    *,
    monday_api_token: str | None = None,
    autentique_api_token: str | None = None,
    dry_run: bool = False,
    max_pages: int = 50,
) -> ControleSyncResult:
    """Cria itens faltantes no Controle Assinaturas a partir do Autentique."""
    monday_token = monday_api_token or get_api_token_from_env()
    if not monday_token:
        raise ControleSyncError("MONDAY_API_TOKEN não configurada.")

    try:
        documents = list_documents(api_token=autentique_api_token, max_pages=max_pages)
    except AutentiqueClientError as exc:
        raise ControleSyncError(str(exc)) from exc

    index = build_controle_assinaturas_index(api_token=monday_token)
    groups = load_controle_board_groups(api_token=monday_token)
    results: list[ControleSyncItemResult] = []
    created = 0
    skipped = 0
    failed = 0
    already = 0

    for document in documents:
        if index.matches_document(document):
            already += 1
            results.append(
                ControleSyncItemResult(
                    document_id=document.document_id,
                    document_name=document.name,
                    action="already_exists",
                ),
            )
            continue

        if dry_run:
            created += 1
            results.append(
                ControleSyncItemResult(
                    document_id=document.document_id,
                    document_name=document.name,
                    action="would_create",
                    detail=_describe_planned_item(document=document, groups=groups),
                ),
            )
            continue

        try:
            item_id, item_url = _create_controle_item(
                api_token=monday_token,
                autentique_api_token=autentique_api_token,
                document=document,
                groups=groups,
            )
        except (MondayClientError, AutentiqueClientError) as exc:
            failed += 1
            results.append(
                ControleSyncItemResult(
                    document_id=document.document_id,
                    document_name=document.name,
                    action="failed",
                    detail=str(exc),
                ),
            )
            continue

        created += 1
        index = index.with_item(
            document_id=document.document_id,
            document_name=document.name,
            signature_link=_build_signature_link_text(
                document=document,
                api_token=autentique_api_token,
            ),
        )
        results.append(
            ControleSyncItemResult(
                document_id=document.document_id,
                document_name=document.name,
                action="created",
                monday_item_id=item_id,
                monday_item_url=item_url,
            ),
        )

    return ControleSyncResult(
        total_autentique=len(documents),
        already_in_monday=already,
        created=created,
        skipped=skipped,
        failed=failed,
        dry_run=dry_run,
        items=tuple(results),
    )


def _create_controle_item(
    *,
    api_token: str,
    autentique_api_token: str | None,
    document: AutentiqueDocumentSummary,
    groups: dict[str, str],
) -> tuple[str, str | None]:
    signature_link = _resolve_signature_link(
        document=document,
        api_token=autentique_api_token,
    )
    tipo = None
    if not is_supplemental_document(document_name=document.name):
        tipo = infer_monday_tipo(
            document_name=document.name,
            category=infer_category(document_name=document.name),
        )
    group_id = _resolve_controle_group_id(document=document, groups=groups)
    status_label = _resolve_controle_status(document=document)
    signed_at = _resolve_signed_at(document=document)

    return create_controle_assinatura_item(
        api_token=api_token,
        item_name=document.name,
        group_id=group_id,
        signature_link_text=signature_link,
        status_label=status_label,
        tipo_label=tipo,
        signed_at=signed_at,
        signed_pdf_url=None,
    )


def _resolve_signature_link(
    *,
    document: AutentiqueDocumentSummary,
    api_token: str | None,
) -> str:
    short_link = document.primary_signature_link()
    if not short_link and document.signatures and api_token:
        for signer in document.signatures:
            if not signer.public_id:
                continue
            try:
                short_link = create_signature_link(public_id=signer.public_id, api_token=api_token)
                break
            except AutentiqueClientError:
                continue
    return _build_signature_link_text(document=document, short_link=short_link)


def _build_signature_link_text(
    *,
    document: AutentiqueDocumentSummary,
    short_link: str | None = None,
    api_token: str | None = None,
) -> str:
    link = short_link or document.primary_signature_link()
    if not link and api_token:
        link = _resolve_signature_link(document=document, api_token=api_token)
    lines = [line for line in (link, f"Autentique ID: {document.document_id}") if line]
    return "\n".join(lines)


def _resolve_controle_group_id(
    *,
    document: AutentiqueDocumentSummary,
    groups: dict[str, str],
) -> str:
    assinados_id = groups.get("assinados", groups.get(CONTROLE_GROUP_ASSINADOS))
    if document.is_fully_signed and assinados_id:
        return assinados_id

    for keyword in ("jan", "pendente", "aguardando"):
        for title, group_id in groups.items():
            if keyword in title and group_id != assinados_id:
                return group_id

    for title, group_id in groups.items():
        if title != "assinados" and group_id != assinados_id:
            return group_id

    return assinados_id or CONTROLE_GROUP_ASSINADOS


def _resolve_controle_status(document: AutentiqueDocumentSummary) -> str:
    if document.is_fully_signed:
        return CONTROLE_STATUS_ASSINADO

    signed_count = sum(1 for signer in document.signatures if signer.signed_at)
    if signed_count > 0:
        return CONTROLE_STATUS_AGUARDANDO_OUTROS
    return "Aguardando Assinatura"


def _resolve_signed_at(document: AutentiqueDocumentSummary) -> date | None:
    signed_dates: list[date] = []
    for signer in document.signatures:
        if not signer.signed_at:
            continue
        parsed = _parse_iso_datetime(signer.signed_at)
        if parsed is not None:
            signed_dates.append(parsed)
    if not signed_dates:
        return None
    return max(signed_dates)


def _parse_iso_datetime(value: str) -> date | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    normalized = cleaned.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def _describe_planned_item(*, document: AutentiqueDocumentSummary, groups: dict[str, str]) -> str:
    payload = {
        "group_id": _resolve_controle_group_id(document=document, groups=groups),
        "status": _resolve_controle_status(document=document),
        "tipo": infer_monday_tipo(
            document_name=document.name,
            category=infer_category(document_name=document.name),
        ),
        "signed": document.is_fully_signed,
    }
    return json.dumps(payload, ensure_ascii=False)
