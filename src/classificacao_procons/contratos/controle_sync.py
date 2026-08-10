"""Sincroniza documentos do Autentique com o quadro Controle Assinaturas."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from classificacao_procons.contratos.autentique.client import (
    AutentiqueClientError,
    AutentiqueDocumentSummary,
    AutentiqueSigner,
    create_signature_link,
    fetch_document_summary,
    list_documents,
)
from classificacao_procons.contratos.autentique.webhook import AutentiqueWebhookEvent
from classificacao_procons.contratos.constants import (
    CONTROLE_GROUP_ASSINADOS,
    CONTROLE_LINK_TRACK_JAN,
    CONTROLE_LINK_TRACK_LUCIANO,
    CONTROLE_STATUS_ASSINADO,
)
from classificacao_procons.contratos.controle_autentique_link import (
    autentique_ids_in_controle_link,
    pick_primary_autentique_document_id_for_item,
    rebuild_controle_signature_link_text,
)
from classificacao_procons.contratos.controle_autentique_plan import (
    ControlePlanAction,
    build_controle_autentique_plan,
    classify_autentique_document_for_controle,
    find_legacy_rows_to_link,
    plan_action_counts,
)
from classificacao_procons.contratos.controle_autentique_terminal import (
    document_is_refused_or_blocked,
)
from classificacao_procons.contratos.controle_compare_diagnostics import (
    ControleCompareDiagnosticSummary,
    ControleDocumentDiagnosticRow,
    build_controle_compare_diagnostics,
    summarize_controle_compare_diagnostics,
)
from classificacao_procons.contratos.controle_create_allowlist import controle_may_create_new_item
from classificacao_procons.contratos.controle_create_policy import (
    controle_create_paused_message,
)
from classificacao_procons.contratos.controle_dedup import (
    controle_title_kind_conflict,
)
from classificacao_procons.contratos.controle_idempotency import (
    build_controle_create_idempotency_key,
)
from classificacao_procons.contratos.controle_legacy_guard import (
    should_block_create_for_signed_autentique,
)
from classificacao_procons.contratos.controle_link_suggestions import (
    ControleLinkSuggestion,
    auto_link_unambiguous_legacy_controle,
    suggest_legacy_controle_links,
)
from classificacao_procons.contratos.controle_reconcile import (
    find_duplicate_autentique_ids,
    find_duplicate_normalized_names,
    find_monday_items_with_multiple_autentique_ids,
    find_monday_status_behind_autentique,
    find_monday_track_status_mismatch,
)
from classificacao_procons.contratos.controle_required_tracks import (
    document_required_controle_tracks,
    resolve_expected_tracks,
)
from classificacao_procons.contratos.controle_scope import (
    ControleScopeClassification,
    classify_controle_scope,
)
from classificacao_procons.contratos.controle_status import (
    resolve_controle_status_document,
    resolve_controle_status_for_track,
    resolve_signed_at_document,
    resolve_signed_at_for_track,
)
from classificacao_procons.contratos.controle_tipo import resolve_controle_tipo_label
from classificacao_procons.contratos.controle_track_repair import (
    CONTROLE_PLATFORM_AUTENTIQUE,
    CONTROLE_SIGNER_LABEL_JAN,
    CONTROLE_SIGNER_LABEL_LUCIANO,
    controle_dual_tracks_satisfied_for_items,
    ensure_controle_dual_tracks_for_document,
    parse_autentique_created_date,
)
from classificacao_procons.contratos.gemini_extractor import ContractMetadata
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import (
    ControleAssinaturasIndex,
    build_controle_assinaturas_index,
    create_controle_assinatura_item,
    ensure_autentique_id_on_controle_items,
    find_controle_items_by_autentique_id,
    infer_controle_signer_track,
    is_controle_contratos_trigger_item,
    load_controle_board_groups,
    update_controle_item_progress,
    update_controle_item_signature_link,
)
from classificacao_procons.contratos.signer_identity import find_jan_signer, find_luciano_signer
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
    updated: int
    skipped: int
    failed: int
    dry_run: bool
    items: tuple[ControleSyncItemResult, ...]
    deferred_signed: int = 0
    legacy_linked: int = 0
    legacy_link_would_apply: int = 0
    legacy_link_ambiguous_skipped: int = 0
    legacy_link_failed: int = 0
    create_paused: int = 0


@dataclass(frozen=True)
class ControleAutentiqueCompareResult:
    """Comparação somente leitura Autentique ↔ Controle Assinaturas."""

    autentique_total: int
    monday_items_total: int
    pending_missing_in_monday: tuple[tuple[str, str], ...]
    signed_missing_in_monday: tuple[tuple[str, str], ...]
    monday_without_autentique_link: tuple[tuple[str, str, str | None], ...]
    monday_autentique_id_not_in_feed: tuple[tuple[str, str, str], ...]
    duplicate_autentique_ids: tuple[tuple[str, tuple[str, ...]], ...] = ()
    duplicate_normalized_names: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    monday_status_behind_autentique: tuple[tuple[str, str, str, str | None, str], ...] = ()
    monday_track_status_mismatch: tuple[
        tuple[str, str, str, str | None, str, str],
        ...,
    ] = ()
    legacy_link_suggestions: tuple[ControleLinkSuggestion, ...] = ()
    monday_multiple_autentique_ids: tuple[tuple[str, str, tuple[str, ...]], ...] = ()
    plan_action_counts: dict[str, int] = field(default_factory=dict)
    document_diagnostics: tuple[ControleDocumentDiagnosticRow, ...] = ()
    diagnostic_summary: ControleCompareDiagnosticSummary | None = None


@dataclass(frozen=True)
class ControleCanonicalLinkRepairItem:
    item_id: str
    item_name: str
    previous_ids: tuple[str, ...]
    canonical_id: str
    updated: bool
    skipped: bool
    skip_reason: str | None = None


@dataclass(frozen=True)
class ControleCanonicalLinkRepairResult:
    dry_run: bool
    items: tuple[ControleCanonicalLinkRepairItem, ...]


@dataclass(frozen=True)
class ControleMismatchReconcileRowResult:
    document_id: str
    document_name: str
    monday_item_id: str
    source: str
    updated: bool
    skipped: bool
    skip_reason: str | None = None
    error: str | None = None
    status_label: str | None = None


@dataclass(frozen=True)
class ControleMismatchReconcileResult:
    dry_run: bool
    track_mismatch_documents: int
    status_behind_documents: int
    updated: int
    skipped: int
    failed: int
    items: tuple[ControleMismatchReconcileRowResult, ...]


@dataclass(frozen=True)
class ControleReconcileResult:
    document_id: str
    document_name: str
    monday_item_id: str | None
    updated: bool
    skipped: bool
    skip_reason: str | None = None
    group_id: str | None = None
    status_label: str | None = None


@dataclass(frozen=True)
class ControleRegistrationResult:
    document_id: str
    document_name: str
    monday_item_id: str | None
    monday_item_url: str | None
    skipped_duplicate: bool = False
    group_id: str | None = None
    status_label: str | None = None
    tipo_filled: bool = False
    mirror_monday_item_id: str | None = None
    create_paused: bool = False


def register_document_in_controle(
    *,
    document_id: str,
    document_name: str | None = None,
    monday_api_token: str | None = None,
    autentique_api_token: str | None = None,
) -> ControleRegistrationResult:
    """Cria item no Controle Assinaturas para um documento do Autentique (se ainda não existir)."""
    monday_token = monday_api_token or get_api_token_from_env()
    if not monday_token:
        raise ControleSyncError("MONDAY_API_TOKEN não configurada.")

    try:
        document = fetch_document_summary(document_id=document_id, api_token=autentique_api_token)
    except AutentiqueClientError as exc:
        raise ControleSyncError(str(exc)) from exc

    if find_controle_items_by_autentique_id(
        api_token=monday_token,
        document_id=document.document_id,
    ):
        groups = load_controle_board_groups(api_token=monday_token)
        jan_group_id, luciano_group_id = _resolve_signer_group_ids(groups)
        if jan_group_id and luciano_group_id:
            ensure_controle_dual_tracks_for_document(
                api_token=monday_token,
                document=document,
                jan_group_id=jan_group_id,
                luciano_group_id=luciano_group_id,
                tipo_label=_resolve_tipo_label(document_name=document.name),
                status_label=_resolve_controle_status(document=document),
                signed_at=_resolve_signed_at(document=document),
                build_track_link=_build_track_signature_link,
                allow_create=controle_may_create_new_item(document_name=document.name),
            )
        return ControleRegistrationResult(
            document_id=document.document_id,
            document_name=document.name,
            monday_item_id=None,
            monday_item_url=None,
            skipped_duplicate=True,
        )

    index = build_controle_assinaturas_index(api_token=monday_token)
    plan_row = classify_autentique_document_for_controle(
        document=document,
        index=index,
    )

    if plan_row.action == ControlePlanAction.CRIAR and not controle_may_create_new_item(
        document_name=document.name,
    ):
        return ControleRegistrationResult(
            document_id=document.document_id,
            document_name=document.name,
            monday_item_id=None,
            monday_item_url=None,
            create_paused=True,
        )

    groups = load_controle_board_groups(api_token=monday_token)
    jan_group_id, luciano_group_id = _resolve_signer_group_ids(groups)
    tipo_label = _resolve_tipo_label(document_name=document.name)
    status_label = _resolve_controle_status(document=document)
    signed_at = _resolve_signed_at(document=document)
    allow_create = controle_may_create_new_item(document_name=document.name)

    def _repair_dual_tracks() -> None:
        if jan_group_id and luciano_group_id:
            ensure_controle_dual_tracks_for_document(
                api_token=monday_token,
                document=document,
                jan_group_id=jan_group_id,
                luciano_group_id=luciano_group_id,
                tipo_label=tipo_label,
                status_label=status_label,
                signed_at=signed_at,
                build_track_link=_build_track_signature_link,
                allow_create=allow_create,
            )

    if plan_row.action == ControlePlanAction.ATUALIZAR:
        _repair_dual_tracks()
        linked = index.items_for_document_id(document.document_id)
        primary_id = linked[0].item_id if linked else None
        return ControleRegistrationResult(
            document_id=document.document_id,
            document_name=document.name,
            monday_item_id=primary_id,
            monday_item_url=None,
            skipped_duplicate=True,
        )

    if plan_row.action == ControlePlanAction.VINCULAR:
        link_targets = find_legacy_rows_to_link(document=document, index=index)
        ensure_autentique_id_on_controle_items(
            api_token=monday_token,
            document_id=document.document_id,
            items=link_targets,
        )
        reconcile_controle_from_document(
            document=document,
            controle_items=link_targets,
            api_token=monday_token,
            groups=groups,
        )
        _repair_dual_tracks()
        return ControleRegistrationResult(
            document_id=document.document_id,
            document_name=document.name,
            monday_item_id=link_targets[0].item_id if link_targets else None,
            monday_item_url=None,
            skipped_duplicate=True,
        )

    if plan_row.action == ControlePlanAction.IGNORAR:
        return ControleRegistrationResult(
            document_id=document.document_id,
            document_name=document.name,
            monday_item_id=plan_row.monday_item_ids[0] if plan_row.monday_item_ids else None,
            monday_item_url=None,
            skipped_duplicate=True,
        )

    if plan_row.action != ControlePlanAction.CRIAR:
        raise ControleSyncError(f"Ação de plano inesperada: {plan_row.action}")

    try:
        item_id, item_url, mirror_id = _create_controle_track_pair(
            api_token=monday_token,
            autentique_api_token=autentique_api_token,
            document=document,
            groups=groups,
            tipo_label=tipo_label,
        )
    except (MondayClientError, AutentiqueClientError) as exc:
        raise ControleSyncError(str(exc)) from exc

    jan_group_id, luciano_group_id = _resolve_signer_group_ids(groups)
    required = document_required_controle_tracks(document)
    primary_group_id = (
        jan_group_id
        if "jan" in required
        else luciano_group_id
        if "luciano" in required
        else jan_group_id
    )

    return ControleRegistrationResult(
        document_id=document.document_id,
        document_name=document.name,
        monday_item_id=item_id,
        monday_item_url=item_url,
        mirror_monday_item_id=mirror_id,
        group_id=primary_group_id,
        status_label=_resolve_controle_status(document=document),
        tipo_filled=tipo_label is not None,
    )


def process_document_created_webhook_event(
    event: AutentiqueWebhookEvent,
    *,
    monday_api_token: str | None = None,
    autentique_api_token: str | None = None,
) -> ControleRegistrationResult:
    """Processa evento document.created do Autentique."""
    if event.event_type != "document.created":
        raise ControleSyncError(f"Evento não suportado: {event.event_type}")

    return register_document_in_controle(
        document_id=event.document_id,
        document_name=event.document_name or None,
        monday_api_token=monday_api_token,
        autentique_api_token=autentique_api_token,
    )


def process_signature_accepted_webhook_event(
    event: AutentiqueWebhookEvent,
    *,
    monday_api_token: str | None = None,
    autentique_api_token: str | None = None,
) -> ControleReconcileResult | ControleRegistrationResult:
    """Processa evento signature.accepted do Autentique."""
    if event.event_type != "signature.accepted":
        raise ControleSyncError(f"Evento não suportado: {event.event_type}")

    return _process_signature_progress_webhook_event(
        event,
        monday_api_token=monday_api_token,
        autentique_api_token=autentique_api_token,
    )


def process_signature_rejected_webhook_event(
    event: AutentiqueWebhookEvent,
    *,
    monday_api_token: str | None = None,
    autentique_api_token: str | None = None,
) -> ControleReconcileResult | ControleRegistrationResult:
    """Processa evento signature.rejected do Autentique (coluna Status = Recusado)."""
    if event.event_type != "signature.rejected":
        raise ControleSyncError(f"Evento não suportado: {event.event_type}")

    return _process_signature_progress_webhook_event(
        event,
        monday_api_token=monday_api_token,
        autentique_api_token=autentique_api_token,
    )


def _process_signature_progress_webhook_event(
    event: AutentiqueWebhookEvent,
    *,
    monday_api_token: str | None = None,
    autentique_api_token: str | None = None,
) -> ControleReconcileResult | ControleRegistrationResult:
    monday_token = monday_api_token or get_api_token_from_env()
    if not monday_token:
        raise ControleSyncError("MONDAY_API_TOKEN não configurada.")

    existing_items = find_controle_items_by_autentique_id(
        api_token=monday_token,
        document_id=event.document_id,
    )
    if not existing_items:
        return register_document_in_controle(
            document_id=event.document_id,
            document_name=event.document_name or None,
            monday_api_token=monday_token,
            autentique_api_token=autentique_api_token,
        )

    try:
        document = fetch_document_summary(
            document_id=event.document_id,
            api_token=autentique_api_token,
        )
    except AutentiqueClientError as exc:
        raise ControleSyncError(str(exc)) from exc

    groups = load_controle_board_groups(api_token=monday_token)
    try:
        return reconcile_controle_from_document(
            document=document,
            controle_items=existing_items,
            api_token=monday_token,
            groups=groups,
        )
    except MondayClientError as exc:
        raise ControleSyncError(str(exc)) from exc


def reconcile_controle_from_document(
    *,
    document: AutentiqueDocumentSummary,
    controle_items: tuple[ControleAssinaturasItem, ...],
    api_token: str,
    groups: dict[str, str],
    dry_run: bool = False,
) -> ControleReconcileResult:
    """Alinha itens do Controle (uma ou duas filas Jan/Luciano) com o Autentique."""
    if len(controle_items) >= 2:
        return _reconcile_dual_track_items(
            document=document,
            controle_items=controle_items,
            api_token=api_token,
            groups=groups,
            dry_run=dry_run,
        )
    if len(controle_items) == 1:
        return reconcile_controle_item_from_document(
            document=document,
            controle_item=controle_items[0],
            api_token=api_token,
            groups=groups,
            dry_run=dry_run,
        )
    return ControleReconcileResult(
        document_id=document.document_id,
        document_name=document.name,
        monday_item_id=None,
        updated=False,
        skipped=True,
        skip_reason="no_controle_item",
    )


def reconcile_controle_item_from_document(
    *,
    document: AutentiqueDocumentSummary,
    controle_item: ControleAssinaturasItem,
    api_token: str,
    groups: dict[str, str],
    dry_run: bool = False,
) -> ControleReconcileResult:
    """Alinha status e grupo do item Monday com o estado atual no Autentique."""
    if controle_title_kind_conflict(document.name, controle_item.name):
        return ControleReconcileResult(
            document_id=document.document_id,
            document_name=document.name,
            monday_item_id=controle_item.item_id,
            updated=False,
            skipped=True,
            skip_reason="title_kind_mismatch",
        )

    if _status_matches(controle_item.status, CONTROLE_STATUS_ASSINADO):
        if not document_is_refused_or_blocked(document):
            return ControleReconcileResult(
                document_id=document.document_id,
                document_name=document.name,
                monday_item_id=controle_item.item_id,
                updated=False,
                skipped=True,
                skip_reason="already_assinado",
            )

    if document.is_fully_signed:
        planned_status = CONTROLE_STATUS_ASSINADO
        track = infer_controle_signer_track(controle_item)
        planned_signed_at = (
            resolve_signed_at_for_track(document, track=track)
            if track in ("jan", "luciano")
            else resolve_signed_at_document(document)
        )
        if _status_matches(controle_item.status, planned_status):
            return ControleReconcileResult(
                document_id=document.document_id,
                document_name=document.name,
                monday_item_id=controle_item.item_id,
                updated=False,
                skipped=True,
                skip_reason="already_assinado",
            )
        if dry_run:
            return ControleReconcileResult(
                document_id=document.document_id,
                document_name=document.name,
                monday_item_id=controle_item.item_id,
                updated=True,
                skipped=False,
                status_label=planned_status,
            )
        update_controle_item_progress(
            api_token=api_token,
            item_id=controle_item.item_id,
            group_id=controle_item.group_id or "",
            status_label=planned_status,
            signed_at=planned_signed_at,
            current_group_id=controle_item.group_id,
        )
        return ControleReconcileResult(
            document_id=document.document_id,
            document_name=document.name,
            monday_item_id=controle_item.item_id,
            updated=True,
            skipped=False,
            status_label=planned_status,
        )

    planned_group_id = _resolve_controle_group_id(document=document, groups=groups)
    track = infer_controle_signer_track(controle_item)
    if track in ("jan", "luciano"):
        planned_status = resolve_controle_status_for_track(document, track=track)
        planned_signed_at = resolve_signed_at_for_track(document, track=track)
    else:
        planned_status = resolve_controle_status_document(document)
        planned_signed_at = resolve_signed_at_document(document)

    status_changed = not _status_matches(controle_item.status, planned_status)
    group_changed = controle_item.group_id != planned_group_id
    if not status_changed and not group_changed:
        return ControleReconcileResult(
            document_id=document.document_id,
            document_name=document.name,
            monday_item_id=controle_item.item_id,
            updated=False,
            skipped=True,
            skip_reason="already_up_to_date",
            group_id=planned_group_id,
            status_label=planned_status,
        )

    if dry_run:
        return ControleReconcileResult(
            document_id=document.document_id,
            document_name=document.name,
            monday_item_id=controle_item.item_id,
            updated=True,
            skipped=False,
            group_id=planned_group_id,
            status_label=planned_status,
        )

    update_controle_item_progress(
        api_token=api_token,
        item_id=controle_item.item_id,
        group_id=planned_group_id,
        status_label=planned_status,
        signed_at=planned_signed_at,
        current_group_id=controle_item.group_id,
    )
    return ControleReconcileResult(
        document_id=document.document_id,
        document_name=document.name,
        monday_item_id=controle_item.item_id,
        updated=True,
        skipped=False,
        group_id=planned_group_id,
        status_label=planned_status,
    )


def compare_autentique_with_controle(
    *,
    monday_api_token: str | None = None,
    autentique_api_token: str | None = None,
    max_pages: int = 50,
) -> ControleAutentiqueCompareResult:
    """Lista diferenças entre Autentique e Controle sem gravar no Monday."""
    monday_token = monday_api_token or get_api_token_from_env()
    if not monday_token:
        raise ControleSyncError("MONDAY_API_TOKEN não configurada.")

    try:
        documents = list_documents(api_token=autentique_api_token, max_pages=max_pages)
    except AutentiqueClientError as exc:
        raise ControleSyncError(str(exc)) from exc

    index = build_controle_assinaturas_index(api_token=monday_token)
    documents_by_id = {
        document.document_id.casefold().strip(): document for document in documents
    }
    autentique_ids = set(documents_by_id.keys())

    plan_rows = build_controle_autentique_plan(documents=documents, index=index)
    plan_counts = plan_action_counts(plan_rows)
    diagnostic_rows = build_controle_compare_diagnostics(documents=documents, index=index)
    diagnostic_summary = summarize_controle_compare_diagnostics(diagnostic_rows)

    pending_missing: list[tuple[str, str]] = []
    signed_missing: list[tuple[str, str]] = []
    for row in plan_rows:
        if row.action != ControlePlanAction.CRIAR:
            continue
        document = documents_by_id.get(row.document_id.casefold().strip())
        if document is None:
            continue
        scope, _ = classify_controle_scope(
            document,
            expected_tracks=resolve_expected_tracks(document),
        )
        if scope != ControleScopeClassification.ELIGIBLE:
            continue
        pair = (row.document_id, row.document_name)
        if row.autentique_fully_signed:
            signed_missing.append(pair)
        else:
            pending_missing.append(pair)

    without_link: list[tuple[str, str, str | None]] = []
    id_not_in_feed: list[tuple[str, str, str]] = []
    for item in index.all_items:
        item_doc_ids = {
            indexed_id
            for indexed_id, indexed_item in index.items_by_document_id
            if indexed_item.item_id == item.item_id
        }
        if not item_doc_ids:
            without_link.append((item.item_id, item.name, item.status))
            continue
        for doc_id in item_doc_ids:
            if doc_id not in autentique_ids:
                id_not_in_feed.append((item.item_id, item.name, doc_id))

    pending_for_suggestions = tuple(
        document
        for document in documents
        if index.get_item(document.document_id) is None
    )
    link_suggestions = suggest_legacy_controle_links(
        index=index,
        pending_documents=pending_for_suggestions,
    )

    return ControleAutentiqueCompareResult(
        autentique_total=len(documents),
        monday_items_total=len(index.all_items),
        pending_missing_in_monday=tuple(pending_missing),
        signed_missing_in_monday=tuple(signed_missing),
        monday_without_autentique_link=tuple(without_link),
        monday_autentique_id_not_in_feed=tuple(id_not_in_feed),
        duplicate_autentique_ids=find_duplicate_autentique_ids(index),
        duplicate_normalized_names=find_duplicate_normalized_names(index),
        monday_status_behind_autentique=find_monday_status_behind_autentique(
            index=index,
            documents_by_id=documents_by_id,
        ),
        monday_track_status_mismatch=find_monday_track_status_mismatch(
            index=index,
            documents_by_id=documents_by_id,
        ),
        legacy_link_suggestions=link_suggestions,
        monday_multiple_autentique_ids=find_monday_items_with_multiple_autentique_ids(index),
        plan_action_counts=plan_counts,
        document_diagnostics=diagnostic_rows,
        diagnostic_summary=diagnostic_summary,
    )


def repair_controle_canonical_autentique_links(
    *,
    monday_api_token: str | None = None,
    autentique_api_token: str | None = None,
    max_pages: int = 50,
    dry_run: bool = False,
) -> ControleCanonicalLinkRepairResult:
    """Reduz o link do Controle a um único Autentique ID canônico por item Monday."""
    monday_token = monday_api_token or get_api_token_from_env()
    if not monday_token:
        raise ControleSyncError("MONDAY_API_TOKEN não configurada.")

    try:
        documents = list_documents(api_token=autentique_api_token, max_pages=max_pages)
    except AutentiqueClientError as exc:
        raise ControleSyncError(str(exc)) from exc

    documents_by_id = {
        document.document_id.casefold().strip(): document for document in documents
    }
    index = build_controle_assinaturas_index(api_token=monday_token)
    multi = find_monday_items_with_multiple_autentique_ids(index)
    items_out: list[ControleCanonicalLinkRepairItem] = []

    item_by_id = {item.item_id: item for item in index.all_items}
    for item_id, item_name, previous_ids in multi:
        item = item_by_id.get(item_id)
        if item is None:
            items_out.append(
                ControleCanonicalLinkRepairItem(
                    item_id=item_id,
                    item_name=item_name,
                    previous_ids=previous_ids,
                    canonical_id="",
                    updated=False,
                    skipped=True,
                    skip_reason="item_not_in_index",
                ),
            )
            continue
        canonical_id = pick_primary_autentique_document_id_for_item(
            item,
            documents_by_id=documents_by_id,
        )
        if canonical_id is None:
            items_out.append(
                ControleCanonicalLinkRepairItem(
                    item_id=item_id,
                    item_name=item_name,
                    previous_ids=previous_ids,
                    canonical_id="",
                    updated=False,
                    skipped=True,
                    skip_reason="no_canonical_id",
                ),
            )
            continue
        link_text = rebuild_controle_signature_link_text(
            previous_link=item.signature_link,
            document_id=canonical_id,
        )
        if dry_run:
            items_out.append(
                ControleCanonicalLinkRepairItem(
                    item_id=item_id,
                    item_name=item_name,
                    previous_ids=previous_ids,
                    canonical_id=canonical_id,
                    updated=True,
                    skipped=False,
                ),
            )
            continue
        try:
            update_controle_item_signature_link(
                api_token=monday_token,
                item_id=item_id,
                signature_link_text=link_text,
            )
        except MondayClientError as exc:
            items_out.append(
                ControleCanonicalLinkRepairItem(
                    item_id=item_id,
                    item_name=item_name,
                    previous_ids=previous_ids,
                    canonical_id=canonical_id,
                    updated=False,
                    skipped=True,
                    skip_reason=f"monday_error: {exc}",
                ),
            )
            continue
        items_out.append(
            ControleCanonicalLinkRepairItem(
                item_id=item_id,
                item_name=item_name,
                previous_ids=previous_ids,
                canonical_id=canonical_id,
                updated=True,
                skipped=False,
            ),
        )

    return ControleCanonicalLinkRepairResult(dry_run=dry_run, items=tuple(items_out))


def _monday_inactive_item_error(exc: BaseException) -> bool:
    return "inactive items" in str(exc).casefold()


def _documents_by_id_for_controle_reconcile(
    *,
    index: ControleAssinaturasIndex,
    autentique_api_token: str | None,
    max_pages: int,
    light_feed: bool,
) -> dict[str, AutentiqueDocumentSummary]:
    """Carrega metadados Autentique para reconciliação (feed completo ou só IDs do Monday)."""
    if not light_feed:
        try:
            documents = list_documents(api_token=autentique_api_token, max_pages=max_pages)
        except AutentiqueClientError as exc:
            raise ControleSyncError(str(exc)) from exc
        return {
            document.document_id.casefold().strip(): document for document in documents
        }

    wanted: set[str] = set()
    for item in index.all_items:
        for token in autentique_ids_in_controle_link(item.signature_link):
            wanted.add(token.casefold().strip())
    documents_by_id: dict[str, AutentiqueDocumentSummary] = {}
    for doc_id in sorted(wanted):
        try:
            document = fetch_document_summary(
                document_id=doc_id,
                api_token=autentique_api_token,
            )
        except AutentiqueClientError:
            continue
        documents_by_id[document.document_id.casefold().strip()] = document
    return documents_by_id


def reconcile_controle_compare_mismatches(
    *,
    monday_api_token: str | None = None,
    autentique_api_token: str | None = None,
    max_pages: int = 50,
    dry_run: bool = False,
    include_status_behind: bool = True,
    light_feed: bool = False,
) -> ControleMismatchReconcileResult:
    """Atualiza no Monday só itens com divergência do compare (track/status)."""
    monday_token = monday_api_token or get_api_token_from_env()
    if not monday_token:
        raise ControleSyncError("MONDAY_API_TOKEN não configurada.")

    index = build_controle_assinaturas_index(api_token=monday_token)
    documents_by_id = _documents_by_id_for_controle_reconcile(
        index=index,
        autentique_api_token=autentique_api_token,
        max_pages=max_pages,
        light_feed=light_feed,
    )
    groups = load_controle_board_groups(api_token=monday_token)

    track_rows = find_monday_track_status_mismatch(
        index=index,
        documents_by_id=documents_by_id,
    )
    behind_rows: tuple[tuple[str, str, str, str | None, str], ...] = ()
    if include_status_behind:
        behind_rows = find_monday_status_behind_autentique(
            index=index,
            documents_by_id=documents_by_id,
        )

    work: dict[str, tuple[str, str, str]] = {}
    for item_id, name, doc_id, *_rest in track_rows:
        normalized = doc_id.casefold().strip()
        work[normalized] = (item_id, name, "track_mismatch")
    for item_id, name, doc_id, *_rest in behind_rows:
        normalized = doc_id.casefold().strip()
        work.setdefault(normalized, (item_id, name, "status_behind"))

    items_out: list[ControleMismatchReconcileRowResult] = []
    updated = 0
    skipped = 0
    failed = 0

    for doc_id, (sample_item_id, sample_name, source) in sorted(work.items()):
        document = documents_by_id.get(doc_id)
        if document is None:
            try:
                document = fetch_document_summary(
                    document_id=doc_id,
                    api_token=autentique_api_token,
                )
            except AutentiqueClientError as exc:
                failed += 1
                items_out.append(
                    ControleMismatchReconcileRowResult(
                        document_id=doc_id,
                        document_name=sample_name,
                        monday_item_id=sample_item_id,
                        source=source,
                        updated=False,
                        skipped=False,
                        error=str(exc),
                    ),
                )
                continue

        controle_items = index.items_for_document_id(doc_id)
        if not controle_items:
            sample = next(
                (item for item in index.all_items if item.item_id == sample_item_id),
                None,
            )
            controle_items = (sample,) if sample is not None else ()

        if not controle_items:
            skipped += 1
            items_out.append(
                ControleMismatchReconcileRowResult(
                    document_id=document.document_id,
                    document_name=document.name,
                    monday_item_id=sample_item_id,
                    source=source,
                    updated=False,
                    skipped=True,
                    skip_reason="no_controle_item",
                ),
            )
            continue

        try:
            reconcile = reconcile_controle_from_document(
                document=document,
                controle_items=controle_items,
                api_token=monday_token,
                groups=groups,
                dry_run=dry_run,
            )
        except MondayClientError as exc:
            if _monday_inactive_item_error(exc):
                skipped += 1
                items_out.append(
                    ControleMismatchReconcileRowResult(
                        document_id=document.document_id,
                        document_name=document.name,
                        monday_item_id=sample_item_id,
                        source=source,
                        updated=False,
                        skipped=True,
                        skip_reason="monday_inactive_item",
                        error=str(exc),
                    ),
                )
            else:
                failed += 1
                items_out.append(
                    ControleMismatchReconcileRowResult(
                        document_id=document.document_id,
                        document_name=document.name,
                        monday_item_id=sample_item_id,
                        source=source,
                        updated=False,
                        skipped=False,
                        error=str(exc),
                    ),
                )
            continue

        if reconcile.updated:
            updated += 1
            items_out.append(
                ControleMismatchReconcileRowResult(
                    document_id=document.document_id,
                    document_name=document.name,
                    monday_item_id=reconcile.monday_item_id or sample_item_id,
                    source=source,
                    updated=True,
                    skipped=False,
                    status_label=reconcile.status_label,
                ),
            )
        else:
            skipped += 1
            items_out.append(
                ControleMismatchReconcileRowResult(
                    document_id=document.document_id,
                    document_name=document.name,
                    monday_item_id=reconcile.monday_item_id or sample_item_id,
                    source=source,
                    updated=False,
                    skipped=True,
                    skip_reason=reconcile.skip_reason,
                    status_label=reconcile.status_label,
                ),
            )

    return ControleMismatchReconcileResult(
        dry_run=dry_run,
        track_mismatch_documents=len(
            {row[2].casefold().strip() for row in track_rows},
        ),
        status_behind_documents=len(
            {row[2].casefold().strip() for row in behind_rows},
        ),
        updated=updated,
        skipped=skipped,
        failed=failed,
        items=tuple(items_out),
    )


def sync_controle_from_autentique(
    *,
    monday_api_token: str | None = None,
    autentique_api_token: str | None = None,
    dry_run: bool = False,
    max_pages: int = 50,
    update_existing: bool = True,
    skip_signed_documents: bool = False,
    auto_link_legacy: bool = True,
    allow_create: bool | None = None,
    import_signed_as_new: bool = False,
) -> ControleSyncResult:
    """Cria ou atualiza itens no Controle Assinaturas a partir do Autentique."""
    monday_token = monday_api_token or get_api_token_from_env()
    if not monday_token:
        raise ControleSyncError("MONDAY_API_TOKEN não configurada.")

    try:
        documents = list_documents(api_token=autentique_api_token, max_pages=max_pages)
    except AutentiqueClientError as exc:
        raise ControleSyncError(str(exc)) from exc

    index = build_controle_assinaturas_index(api_token=monday_token)
    legacy_linked = 0
    legacy_link_would_apply = 0
    legacy_link_ambiguous_skipped = 0
    legacy_link_failed = 0

    if auto_link_legacy:
        try:
            legacy_result = auto_link_unambiguous_legacy_controle(
                api_token=monday_token,
                autentique_api_token=autentique_api_token,
                max_pages=max_pages,
                dry_run=dry_run,
                index=index,
                pending_documents=tuple(
                    document
                    for document in documents
                    if index.get_item(document.document_id) is None
                ),
            )
        except ValueError as exc:
            raise ControleSyncError(str(exc)) from exc
        legacy_linked = legacy_result.applied
        legacy_link_would_apply = legacy_result.would_apply
        legacy_link_ambiguous_skipped = legacy_result.ambiguous_skipped
        legacy_link_failed = legacy_result.failed
        if not dry_run and legacy_result.applied:
            index = build_controle_assinaturas_index(api_token=monday_token)

    groups = load_controle_board_groups(api_token=monday_token)
    results: list[ControleSyncItemResult] = []
    created = 0
    updated = 0
    skipped = 0
    failed = 0
    already = 0
    deferred_signed = 0
    create_paused = 0

    for document in documents:
        doc_may_create = controle_may_create_new_item(
            document_name=document.name,
            allow_create=allow_create,
        )
        track_may_create = doc_may_create and not should_block_create_for_signed_autentique(
            document_name=document.name,
            is_fully_signed=document.is_fully_signed,
            items=index.all_items,
            import_signed_as_new=import_signed_as_new,
        )
        if not dry_run:
            linked_items = index.items_for_document_id(document.document_id)
            if linked_items and not controle_dual_tracks_satisfied_for_items(
                document,
                linked_items,
            ):
                jan_group_id, luciano_group_id = _resolve_signer_group_ids(groups)
                if jan_group_id and luciano_group_id:
                    try:
                        ensure_controle_dual_tracks_for_document(
                            api_token=monday_token,
                            document=document,
                            jan_group_id=jan_group_id,
                            luciano_group_id=luciano_group_id,
                            tipo_label=_resolve_tipo_label(document_name=document.name),
                            status_label=_resolve_controle_status(document=document),
                            signed_at=_resolve_signed_at(document=document),
                            build_track_link=_build_track_signature_link,
                            allow_create=track_may_create,
                        )
                    except MondayClientError as exc:
                        failed += 1
                        results.append(
                            ControleSyncItemResult(
                                document_id=document.document_id,
                                document_name=document.name,
                                action="failed",
                                detail=f"track_repair: {exc}",
                            ),
                        )

        plan_row = classify_autentique_document_for_controle(
            document=document,
            index=index,
            import_signed_as_new=import_signed_as_new,
        )
        plan_action = plan_row.action

        if skip_signed_documents and document.is_fully_signed:
            if plan_action == ControlePlanAction.CRIAR:
                deferred_signed += 1
                results.append(
                    ControleSyncItemResult(
                        document_id=document.document_id,
                        document_name=document.name,
                        action="deferred_signed",
                        detail="fully_signed_not_imported_in_this_phase",
                    ),
                )
                continue
            if (
                plan_action == ControlePlanAction.IGNORAR
                and plan_row.reason == "signed_no_matching_legacy_row"
            ):
                deferred_signed += 1
                results.append(
                    ControleSyncItemResult(
                        document_id=document.document_id,
                        document_name=document.name,
                        action="deferred_signed",
                        detail="fully_signed_not_imported_in_this_phase",
                    ),
                )
                continue

        if plan_action == ControlePlanAction.IGNORAR:
            if plan_row.reason == "ambiguous_legacy_match_manual_link":
                skipped += 1
                ignore_action = "ignored_ambiguous_legacy"
            elif plan_row.reason == "signed_no_matching_legacy_row":
                deferred_signed += 1
                ignore_action = "deferred_signed_no_legacy_match"
            else:
                skipped += 1
                ignore_action = "ignored"
            results.append(
                ControleSyncItemResult(
                    document_id=document.document_id,
                    document_name=document.name,
                    action=ignore_action,
                    monday_item_id=plan_row.monday_item_ids[0]
                    if plan_row.monday_item_ids
                    else None,
                    detail=plan_row.reason,
                ),
            )
            continue

        if plan_action == ControlePlanAction.ATUALIZAR:
            existing_item = index.get_item(document.document_id)
            linked_items = index.items_for_document_id(document.document_id)
            primary_item = existing_item or (linked_items[0] if linked_items else None)
            if primary_item is None:
                already += 1
                results.append(
                    ControleSyncItemResult(
                        document_id=document.document_id,
                        document_name=document.name,
                        action="unchanged",
                        detail="autentique_id_already_on_monday",
                    ),
                )
                continue
            if not update_existing:
                already += 1
                results.append(
                    ControleSyncItemResult(
                        document_id=document.document_id,
                        document_name=document.name,
                        action="unchanged",
                        monday_item_id=primary_item.item_id,
                        detail="update_existing_disabled",
                    ),
                )
                continue
            if dry_run:
                reconcile = reconcile_controle_from_document(
                    document=document,
                    controle_items=_load_controle_items_for_document(
                        api_token=monday_token,
                        document_id=document.document_id,
                        fallback_item=primary_item,
                        index=index,
                    ),
                    api_token=monday_token,
                    groups=groups,
                    dry_run=True,
                )
                action = "would_update" if reconcile.updated else "unchanged"
                if reconcile.updated:
                    updated += 1
                else:
                    already += 1
                results.append(
                    ControleSyncItemResult(
                        document_id=document.document_id,
                        document_name=document.name,
                        action=action,
                        monday_item_id=primary_item.item_id,
                        detail=json.dumps(
                            {
                                "group_id": reconcile.group_id,
                                "status": reconcile.status_label,
                                "skip_reason": reconcile.skip_reason,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                continue

            try:
                reconcile = reconcile_controle_from_document(
                    document=document,
                    controle_items=_load_controle_items_for_document(
                        api_token=monday_token,
                        document_id=document.document_id,
                        fallback_item=primary_item,
                        index=index,
                    ),
                    api_token=monday_token,
                    groups=groups,
                )
            except MondayClientError as exc:
                if _monday_inactive_item_error(exc):
                    skipped += 1
                    results.append(
                        ControleSyncItemResult(
                            document_id=document.document_id,
                            document_name=document.name,
                            action="skipped_inactive",
                            monday_item_id=primary_item.item_id,
                            detail=str(exc),
                        ),
                    )
                else:
                    failed += 1
                    results.append(
                        ControleSyncItemResult(
                            document_id=document.document_id,
                            document_name=document.name,
                            action="failed",
                            monday_item_id=primary_item.item_id,
                            detail=str(exc),
                        ),
                    )
                continue

            if reconcile.updated:
                updated += 1
                results.append(
                    ControleSyncItemResult(
                        document_id=document.document_id,
                        document_name=document.name,
                        action="updated",
                        monday_item_id=primary_item.item_id,
                        detail=json.dumps(
                            {
                                "group_id": reconcile.group_id,
                                "status": reconcile.status_label,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
            else:
                already += 1
                results.append(
                    ControleSyncItemResult(
                        document_id=document.document_id,
                        document_name=document.name,
                        action="unchanged",
                        monday_item_id=primary_item.item_id,
                        detail=reconcile.skip_reason,
                    ),
                )
            continue

        if plan_action == ControlePlanAction.VINCULAR:
            link_targets = find_legacy_rows_to_link(document=document, index=index)
            if dry_run:
                already += 1
                results.append(
                    ControleSyncItemResult(
                        document_id=document.document_id,
                        document_name=document.name,
                        action="would_link_legacy"
                        if update_existing
                        else "would_link_legacy_only",
                        monday_item_id=link_targets[0].item_id if link_targets else None,
                        detail=plan_row.reason,
                    ),
                )
                continue

            ensure_autentique_id_on_controle_items(
                api_token=monday_token,
                document_id=document.document_id,
                items=link_targets,
            )
            reconcile_updated = False
            reconcile_detail: str | None = plan_row.reason
            if update_existing:
                try:
                    reconcile = reconcile_controle_from_document(
                        document=document,
                        controle_items=link_targets,
                        api_token=monday_token,
                        groups=groups,
                    )
                    reconcile_updated = reconcile.updated
                    reconcile_detail = reconcile.skip_reason or plan_row.reason
                except MondayClientError as exc:
                    if _monday_inactive_item_error(exc):
                        skipped += 1
                        results.append(
                            ControleSyncItemResult(
                                document_id=document.document_id,
                                document_name=document.name,
                                action="skipped_inactive",
                                monday_item_id=link_targets[0].item_id,
                                detail=str(exc),
                            ),
                        )
                        continue
                    failed += 1
                    results.append(
                        ControleSyncItemResult(
                            document_id=document.document_id,
                            document_name=document.name,
                            action="failed",
                            monday_item_id=link_targets[0].item_id,
                            detail=str(exc),
                        ),
                    )
                    continue

            jan_group_id, luciano_group_id = _resolve_signer_group_ids(groups)
            if jan_group_id and luciano_group_id:
                try:
                    ensure_controle_dual_tracks_for_document(
                        api_token=monday_token,
                        document=document,
                        jan_group_id=jan_group_id,
                        luciano_group_id=luciano_group_id,
                        tipo_label=_resolve_tipo_label(document_name=document.name),
                        status_label=_resolve_controle_status(document=document),
                        signed_at=_resolve_signed_at(document=document),
                        build_track_link=_build_track_signature_link,
                        allow_create=track_may_create,
                    )
                except MondayClientError as exc:
                    failed += 1
                    results.append(
                        ControleSyncItemResult(
                            document_id=document.document_id,
                            document_name=document.name,
                            action="failed",
                            detail=f"track_repair: {exc}",
                        ),
                    )
                    continue

            if reconcile_updated:
                updated += 1
                link_action = "linked_legacy_and_updated"
            else:
                already += 1
                if document.is_fully_signed:
                    link_action = "linked_legacy_assinado_skip_create"
                else:
                    link_action = "linked_existing_by_name"
            results.append(
                ControleSyncItemResult(
                    document_id=document.document_id,
                    document_name=document.name,
                    action=link_action,
                    monday_item_id=link_targets[0].item_id,
                    detail=reconcile_detail,
                ),
            )
            continue

        if plan_action == ControlePlanAction.CRIAR:
            if document.is_fully_signed:
                deferred_signed += 1
                results.append(
                    ControleSyncItemResult(
                        document_id=document.document_id,
                        document_name=document.name,
                        action="deferred_signed",
                        detail="signed_autentique_never_create",
                    ),
                )
                continue
            if dry_run:
                if not doc_may_create:
                    create_paused += 1
                    results.append(
                        ControleSyncItemResult(
                            document_id=document.document_id,
                            document_name=document.name,
                            action="create_paused",
                            detail=controle_create_paused_message(),
                        ),
                    )
                    continue
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

            if not doc_may_create:
                create_paused += 1
                results.append(
                    ControleSyncItemResult(
                        document_id=document.document_id,
                        document_name=document.name,
                        action="create_paused",
                        detail=controle_create_paused_message(),
                    ),
                )
                continue

            try:
                item_id, item_url, _mirror_id = _create_controle_track_pair(
                    api_token=monday_token,
                    autentique_api_token=autentique_api_token,
                    document=document,
                    groups=groups,
                    tipo_label=_resolve_tipo_label(document_name=document.name),
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
            continue

        skipped += 1
        results.append(
            ControleSyncItemResult(
                document_id=document.document_id,
                document_name=document.name,
                action="skipped",
                detail=f"unhandled_plan_action:{plan_action}",
            ),
        )

    return ControleSyncResult(
        total_autentique=len(documents),
        already_in_monday=already,
        created=created,
        updated=updated,
        skipped=skipped,
        failed=failed,
        dry_run=dry_run,
        items=tuple(results),
        deferred_signed=deferred_signed,
        legacy_linked=legacy_linked,
        legacy_link_would_apply=legacy_link_would_apply,
        legacy_link_ambiguous_skipped=legacy_link_ambiguous_skipped,
        legacy_link_failed=legacy_link_failed,
        create_paused=create_paused,
    )


def _status_matches(current: str | None, expected: str) -> bool:
    if not current:
        return False
    return current.casefold().strip() == expected.casefold().strip()


def _load_controle_items_for_document(
    *,
    api_token: str,
    document_id: str,
    fallback_item: ControleAssinaturasItem,
    index: ControleAssinaturasIndex | None = None,
) -> tuple[ControleAssinaturasItem, ...]:
    if index is not None:
        indexed = index.items_for_document_id(document_id)
        if indexed:
            return indexed
    items = find_controle_items_by_autentique_id(api_token=api_token, document_id=document_id)
    if items:
        return items
    return (fallback_item,)


def _reconcile_dual_track_items(
    *,
    document: AutentiqueDocumentSummary,
    controle_items: tuple[ControleAssinaturasItem, ...],
    api_token: str,
    groups: dict[str, str],
    dry_run: bool = False,
) -> ControleReconcileResult:
    jan_group_id, luciano_group_id = _resolve_signer_group_ids(groups)

    if document.is_fully_signed:
        primary_item = next(
            (item for item in controle_items if is_controle_contratos_trigger_item(item)),
            controle_items[0],
        )
        any_updated = False
        required = document_required_controle_tracks(document)
        for item in controle_items:
            if _status_matches(item.status, CONTROLE_STATUS_ASSINADO):
                continue
            track = infer_controle_signer_track(item)
            if track in ("jan", "luciano") and track not in required:
                continue
            track = infer_controle_signer_track(item)
            signed_at = (
                resolve_signed_at_for_track(document, track=track)
                if track in ("jan", "luciano")
                else resolve_signed_at_document(document)
            )
            if dry_run:
                any_updated = True
                continue
            update_controle_item_progress(
                api_token=api_token,
                item_id=item.item_id,
                group_id=item.group_id or "",
                status_label=CONTROLE_STATUS_ASSINADO,
                signed_at=signed_at,
                current_group_id=item.group_id,
            )
            any_updated = True
        return ControleReconcileResult(
            document_id=document.document_id,
            document_name=document.name,
            monday_item_id=primary_item.item_id,
            updated=any_updated,
            skipped=not any_updated,
            skip_reason=None if any_updated else "already_assinado",
            status_label=CONTROLE_STATUS_ASSINADO,
        )

    primary_item = next(
        (item for item in controle_items if is_controle_contratos_trigger_item(item)),
        controle_items[0],
    )
    any_updated = False
    for item in controle_items:
        if _status_matches(item.status, CONTROLE_STATUS_ASSINADO):
            continue

        track = infer_controle_signer_track(item)
        required = document_required_controle_tracks(document)
        if track in ("jan", "luciano") and track not in required:
            continue

        if track == "jan":
            target_group = jan_group_id or item.group_id or ""
        elif track == "luciano":
            target_group = luciano_group_id or item.group_id or ""
        else:
            target_group = item.group_id or jan_group_id or luciano_group_id or ""

        if track in ("jan", "luciano"):
            planned_status = resolve_controle_status_for_track(document, track=track)
            planned_signed_at = resolve_signed_at_for_track(document, track=track)
        else:
            planned_status = resolve_controle_status_document(document)
            planned_signed_at = resolve_signed_at_document(document)

        status_changed = not _status_matches(item.status, planned_status)
        group_changed = bool(target_group) and item.group_id != target_group
        if not status_changed and not group_changed:
            continue

        if dry_run:
            any_updated = True
            continue

        update_controle_item_progress(
            api_token=api_token,
            item_id=item.item_id,
            group_id=target_group,
            status_label=planned_status,
            signed_at=planned_signed_at,
            current_group_id=item.group_id,
        )
        any_updated = True

    return ControleReconcileResult(
        document_id=document.document_id,
        document_name=document.name,
        monday_item_id=primary_item.item_id,
        updated=any_updated,
        skipped=not any_updated,
        skip_reason=None if any_updated else "already_up_to_date",
        group_id=primary_item.group_id,
        status_label=resolve_controle_status_document(document),
    )


def _create_controle_track_pair(
    *,
    api_token: str,
    autentique_api_token: str | None,
    document: AutentiqueDocumentSummary,
    groups: dict[str, str],
    tipo_label: str | None,
) -> tuple[str, str | None, str | None]:
    """Cria itens Jan e/ou Luciano conforme signatários no Autentique."""
    jan_group_id, luciano_group_id = _resolve_signer_group_ids(groups)
    if not jan_group_id or not luciano_group_id:
        raise ControleSyncError(
            "Grupos Jan e Luciano não encontrados no quadro Controle Assinaturas.",
        )

    required = document_required_controle_tracks(document)
    if not required:
        raise ControleSyncError(
            f"Documento {document.document_id} não tem signatário Jan nem Luciano no Autentique.",
        )

    short_link = _resolve_signature_link(document=document, api_token=autentique_api_token)
    inclusion_date = parse_autentique_created_date(document)

    jan_id: str | None = None
    jan_url: str | None = None
    luciano_id: str | None = None

    if "jan" in required:
        jan_id, jan_url = create_controle_assinatura_item(
            api_token=api_token,
            item_name=document.name,
            group_id=jan_group_id,
            signature_link_text=_build_track_signature_link(
                document=document,
                track="jan",
                short_link=short_link,
            ),
            status_label=resolve_controle_status_for_track(document, track="jan"),
            tipo_label=tipo_label,
            signed_at=resolve_signed_at_for_track(document, track="jan"),
            signed_pdf_url=None,
            signer_label=CONTROLE_SIGNER_LABEL_JAN,
            platform_name=CONTROLE_PLATFORM_AUTENTIQUE,
            inclusion_date=inclusion_date,
            idempotency_key=build_controle_create_idempotency_key(
                autentique_document_id=document.document_id,
                track="jan",
            ),
        )
    if "luciano" in required:
        luciano_id, _luciano_url = create_controle_assinatura_item(
            api_token=api_token,
            item_name=document.name,
            group_id=luciano_group_id,
            signature_link_text=_build_track_signature_link(
                document=document,
                track="luciano",
                short_link=short_link,
            ),
            status_label=resolve_controle_status_for_track(document, track="luciano"),
            tipo_label=None,
            signed_at=resolve_signed_at_for_track(document, track="luciano"),
            signed_pdf_url=None,
            signer_label=CONTROLE_SIGNER_LABEL_LUCIANO,
            platform_name=CONTROLE_PLATFORM_AUTENTIQUE,
            inclusion_date=inclusion_date,
            idempotency_key=build_controle_create_idempotency_key(
                autentique_document_id=document.document_id,
                track="luciano",
            ),
        )

    primary_id = jan_id or luciano_id
    primary_url = jan_url
    mirror_id = luciano_id if jan_id else None
    if primary_id is None:
        raise ControleSyncError("Falha ao criar itens no Controle Assinaturas.")
    return primary_id, primary_url, mirror_id


def _resolve_signer_group_ids(groups: dict[str, str]) -> tuple[str | None, str | None]:
    assinados_id = groups.get("assinados", groups.get(CONTROLE_GROUP_ASSINADOS))
    jan_group_id = _find_group_id_by_keyword(groups, keyword="jan", exclude_id=assinados_id)
    luciano_group_id = _find_group_id_by_keyword(
        groups,
        keyword="luciano",
        exclude_id=assinados_id,
    )
    return jan_group_id, luciano_group_id


def _build_track_signature_link(
    *,
    document: AutentiqueDocumentSummary,
    track: str,
    short_link: str | None,
) -> str:
    marker = CONTROLE_LINK_TRACK_JAN if track == "jan" else CONTROLE_LINK_TRACK_LUCIANO
    base = _build_signature_link_text(document=document, short_link=short_link)
    return f"{base}\n{marker}"


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
    group_id = _resolve_controle_group_id(document=document, groups=groups)
    tipo = _resolve_tipo_label(
        document_name=document.name,
        group_id=group_id,
        groups=groups,
    )
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

    jan_signed = _is_jan_signed(document=document)
    luciano_signed = _is_luciano_signed(document=document)

    jan_group_id = _find_group_id_by_keyword(groups, keyword="jan", exclude_id=assinados_id)
    luciano_group_id = _find_group_id_by_keyword(
        groups,
        keyword="luciano",
        exclude_id=assinados_id,
    )

    if jan_signed and not luciano_signed and luciano_group_id:
        return luciano_group_id
    if luciano_signed and not jan_signed and jan_group_id:
        return jan_group_id

    if not jan_signed and not luciano_signed:
        if luciano_group_id:
            return luciano_group_id
        if jan_group_id:
            return jan_group_id

    if jan_group_id:
        return jan_group_id
    if luciano_group_id:
        return luciano_group_id

    for keyword in ("pendente", "aguardando"):
        group_id = _find_group_id_by_keyword(groups, keyword=keyword, exclude_id=assinados_id)
        if group_id:
            return group_id

    for title, group_id in groups.items():
        if title != "assinados" and group_id != assinados_id:
            return group_id

    return assinados_id or CONTROLE_GROUP_ASSINADOS


def _resolve_tipo_label(
    *,
    document_name: str,
    group_id: str | None = None,
    groups: dict[str, str] | None = None,
    metadata: ContractMetadata | None = None,
    pdf_path: Path | None = None,
    gemini_api_key: str | None = None,
    skip_gemini: bool = False,
) -> str | None:
    del group_id, groups
    return resolve_controle_tipo_label(
        document_name=document_name,
        metadata=metadata,
        pdf_path=pdf_path,
        gemini_api_key=gemini_api_key,
        skip_gemini=skip_gemini,
        min_confidence="low" if pdf_path is None else "medium",
    )


def _find_group_id_by_keyword(
    groups: dict[str, str],
    *,
    keyword: str,
    exclude_id: str | None,
) -> str | None:
    pattern = re.compile(rf"\b{re.escape(keyword)}\b")
    for title, group_id in groups.items():
        if exclude_id and group_id == exclude_id:
            continue
        if pattern.search(_normalize_group_title(title)):
            return group_id
    return None


def _normalize_group_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return without_marks.strip()


def _is_jan_signed(*, document: AutentiqueDocumentSummary) -> bool:
    signer = find_jan_signer(document.signatures)
    return bool(signer and signer.signed_at)


def _is_luciano_signed(*, document: AutentiqueDocumentSummary) -> bool:
    signer = find_luciano_signer(document.signatures)
    return bool(signer and signer.signed_at)


def _find_signer_by_email(
    signatures: tuple[AutentiqueSigner, ...],
    *,
    email: str,
) -> AutentiqueSigner | None:
    target = email.casefold().strip()
    for signer in signatures:
        if signer.email and signer.email.casefold().strip() == target:
            return signer
    return None


def _resolve_controle_status(document: AutentiqueDocumentSummary) -> str:
    return resolve_controle_status_document(document)


def _resolve_signed_at(document: AutentiqueDocumentSummary) -> date | None:
    return resolve_signed_at_document(document)


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
    group_id = _resolve_controle_group_id(document=document, groups=groups)
    payload = {
        "group_id": group_id,
        "status": _resolve_controle_status(document=document),
        "tipo": _resolve_tipo_label(
            document_name=document.name,
            group_id=group_id,
            groups=groups,
        ),
        "signed": document.is_fully_signed,
    }
    return json.dumps(payload, ensure_ascii=False)
