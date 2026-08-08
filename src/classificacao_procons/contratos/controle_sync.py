"""Sincroniza documentos do Autentique com o quadro Controle Assinaturas."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
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
    pick_primary_autentique_document_id_for_item,
    rebuild_controle_signature_link_text,
)
from classificacao_procons.contratos.controle_autentique_terminal import (
    document_is_refused_or_blocked,
)
from classificacao_procons.contratos.controle_create_allowlist import controle_may_create_new_item
from classificacao_procons.contratos.controle_create_policy import (
    controle_create_paused_message,
)
from classificacao_procons.contratos.controle_dedup import (
    controle_title_kind_conflict,
    find_exact_title_matches,
    find_likely_name_matches,
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
    ensure_controle_dual_tracks_for_document,
    parse_autentique_created_date,
)
from classificacao_procons.contratos.gemini_extractor import ContractMetadata
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import (
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
    if index.matches_document(document):
        title_pool = index.pending_track_items or index.all_items
        exact_matches = find_exact_title_matches(
            document_name=document.name,
            items=title_pool,
        )
        if exact_matches and document.document_id.casefold().strip() not in index.document_ids:
            ensure_autentique_id_on_controle_items(
                api_token=monday_token,
                document_id=document.document_id,
                items=exact_matches,
            )
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
            monday_item_id=exact_matches[0].item_id if exact_matches else None,
            monday_item_url=None,
            skipped_duplicate=True,
        )

    if not controle_may_create_new_item(document_name=document.name):
        return ControleRegistrationResult(
            document_id=document.document_id,
            document_name=document.name,
            monday_item_id=None,
            monday_item_url=None,
            create_paused=True,
        )

    groups = load_controle_board_groups(api_token=monday_token)
    tipo_label = _resolve_tipo_label(document_name=document.name)

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

    pending_missing: list[tuple[str, str]] = []
    signed_missing: list[tuple[str, str]] = []
    for document in documents:
        if index.matches_document(document):
            continue
        pair = (document.document_id, document.name)
        if document.is_fully_signed:
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
        if not dry_run:
            linked_items = find_controle_items_by_autentique_id(
                api_token=monday_token,
                document_id=document.document_id,
            )
            if linked_items:
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
                            allow_create=doc_may_create,
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

        if skip_signed_documents and document.is_fully_signed:
            if index.matches_document(document) or index.get_item(document.document_id):
                already += 1
                results.append(
                    ControleSyncItemResult(
                        document_id=document.document_id,
                        document_name=document.name,
                        action="unchanged",
                        detail="signed_deferred",
                    ),
                )
            else:
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

        existing_item = index.get_item(document.document_id)
        if existing_item and update_existing:
            if dry_run:
                reconcile = reconcile_controle_from_document(
                    document=document,
                    controle_items=_load_controle_items_for_document(
                        api_token=monday_token,
                        document_id=document.document_id,
                        fallback_item=existing_item,
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
                        monday_item_id=existing_item.item_id,
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
                        fallback_item=existing_item,
                    ),
                    api_token=monday_token,
                    groups=groups,
                )
            except MondayClientError as exc:
                failed += 1
                results.append(
                    ControleSyncItemResult(
                        document_id=document.document_id,
                        document_name=document.name,
                        action="failed",
                        monday_item_id=existing_item.item_id,
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
                        monday_item_id=existing_item.item_id,
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
                        monday_item_id=existing_item.item_id,
                        detail=reconcile.skip_reason,
                    ),
                )
            continue

        if index.matches_document(document):
            likely = find_likely_name_matches(
                document_name=document.name,
                items=index.all_items,
            )
            missing_autentique_link = (
                document.document_id.casefold().strip() not in index.document_ids
            )
            if likely and missing_autentique_link:
                if not dry_run:
                    ensure_autentique_id_on_controle_items(
                        api_token=monday_token,
                        document_id=document.document_id,
                        items=likely,
                    )
                already += 1
                results.append(
                    ControleSyncItemResult(
                        document_id=document.document_id,
                        document_name=document.name,
                        action="linked_existing_by_name"
                        if not dry_run
                        else "would_link_existing_by_name",
                        monday_item_id=likely[0].item_id,
                        detail=likely[0].name,
                    ),
                )
                continue

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

        likely_unlinked = find_likely_name_matches(
            document_name=document.name,
            items=index.all_items,
        )
        if likely_unlinked and document.document_id.casefold().strip() not in index.document_ids:
            ensure_autentique_id_on_controle_items(
                api_token=monday_token,
                document_id=document.document_id,
                items=likely_unlinked,
            )
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
                        allow_create=doc_may_create,
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
            already += 1
            results.append(
                ControleSyncItemResult(
                    document_id=document.document_id,
                    document_name=document.name,
                    action="linked_existing_by_name",
                    monday_item_id=likely_unlinked[0].item_id,
                    detail=likely_unlinked[0].name,
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
) -> tuple[ControleAssinaturasItem, ...]:
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
