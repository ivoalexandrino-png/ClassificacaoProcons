"""Auditoria de itens criados indevidamente pelo sync (duplicata vs legado Assinado)."""

from __future__ import annotations

from dataclasses import dataclass

from classificacao_procons.contratos.autentique.client import (
    AutentiqueClientError,
    AutentiqueDocumentSummary,
    fetch_document_summary,
    list_documents,
)
from classificacao_procons.contratos.constants import (
    CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
    CONTROLE_STATUS_AGUARDANDO_OUTROS,
)
from classificacao_procons.contratos.controle_autentique_link import (
    autentique_ids_in_controle_link,
)
from classificacao_procons.contratos.controle_legacy_guard import (
    find_legacy_signed_name_matches,
    status_is_assinado,
)
from classificacao_procons.contratos.controle_reconcile import find_duplicate_normalized_names
from classificacao_procons.contratos.controle_write_policy import (
    require_controle_write_unless_dry_run,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import (
    ControleAssinaturasIndex,
    archive_controle_item,
    build_controle_assinaturas_index,
)


def _status_is_pending_sync_noise(status: str | None) -> bool:
    if not status:
        return True
    normalized = status.casefold().strip()
    return normalized in {
        CONTROLE_STATUS_AGUARDANDO_OUTROS.casefold(),
        CONTROLE_STATUS_AGUARDANDO_ASSINATURA.casefold(),
    }


@dataclass(frozen=True)
class ErroneousSyncItemRow:
    item_id: str
    item_name: str
    item_status: str | None
    autentique_document_id: str
    legacy_assinado_item_id: str
    legacy_assinado_item_name: str
    reason: str


@dataclass(frozen=True)
class ErroneousSyncRemediationResult:
    dry_run: bool
    candidates: tuple[ErroneousSyncItemRow, ...]
    archived: int
    failed: int


def _document_fully_signed(
    doc_id: str,
    *,
    documents_by_id: dict[str, AutentiqueDocumentSummary],
    autentique_api_token: str | None,
) -> bool:
    normalized = doc_id.casefold().strip()
    cached = documents_by_id.get(normalized)
    if cached is not None:
        return cached.is_fully_signed
    try:
        fetched = fetch_document_summary(document_id=doc_id, api_token=autentique_api_token)
    except AutentiqueClientError:
        return False
    return fetched.is_fully_signed


def _append_duplicate_normalized_name_candidates(
    *,
    index: ControleAssinaturasIndex,
    documents_by_id: dict[str, AutentiqueDocumentSummary],
    autentique_api_token: str | None,
    pending_ids: set[str],
    seen_item_ids: set[str],
    rows: list[ErroneousSyncItemRow],
) -> None:
    items_by_id = {item.item_id: item for item in index.all_items}
    for _normalized, entries in find_duplicate_normalized_names(index):
        if len(entries) < 2:
            continue
        cluster = [items_by_id[item_id] for item_id, _name in entries if item_id in items_by_id]
        assinados = [item for item in cluster if status_is_assinado(item.status)]
        if not assinados:
            continue
        legacy = assinados[0]
        for item in cluster:
            if item.item_id in seen_item_ids:
                continue
            if item.item_id not in pending_ids:
                continue
            if not _status_is_pending_sync_noise(item.status):
                continue
            linked_ids = autentique_ids_in_controle_link(item.signature_link)
            if not linked_ids:
                continue
            primary_doc_id = linked_ids[-1]
            if not _document_fully_signed(
                primary_doc_id,
                documents_by_id=documents_by_id,
                autentique_api_token=autentique_api_token,
            ):
                continue
            seen_item_ids.add(item.item_id)
            rows.append(
                ErroneousSyncItemRow(
                    item_id=item.item_id,
                    item_name=item.name,
                    item_status=item.status,
                    autentique_document_id=primary_doc_id,
                    legacy_assinado_item_id=legacy.item_id,
                    legacy_assinado_item_name=legacy.name,
                    reason="duplicate_normalized_title_pending_vs_assinado",
                ),
            )


def _append_pending_only_duplicate_candidates(
    *,
    index: ControleAssinaturasIndex,
    documents_by_id: dict[str, AutentiqueDocumentSummary],
    autentique_api_token: str | None,
    pending_ids: set[str],
    seen_item_ids: set[str],
    rows: list[ErroneousSyncItemRow],
) -> None:
    """Vários itens na fila pendente com o mesmo título e doc já assinado (ex.: sync duplo)."""
    items_by_id = {item.item_id: item for item in index.all_items}
    for _normalized, entries in find_duplicate_normalized_names(index):
        if len(entries) < 2:
            continue
        cluster = [items_by_id[item_id] for item_id, _name in entries if item_id in items_by_id]
        pending = [
            item
            for item in cluster
            if item.item_id in pending_ids and _status_is_pending_sync_noise(item.status)
        ]
        if len(pending) < 2:
            continue
        signed_pending: list[ControleAssinaturasItem] = []
        for item in pending:
            linked_ids = autentique_ids_in_controle_link(item.signature_link)
            if not linked_ids:
                continue
            if _document_fully_signed(
                linked_ids[-1],
                documents_by_id=documents_by_id,
                autentique_api_token=autentique_api_token,
            ):
                signed_pending.append(item)
        if len(signed_pending) < 2:
            continue
        signed_pending.sort(key=lambda row: int(row.item_id))
        keeper = signed_pending[0]
        for extra in signed_pending[1:]:
            if extra.item_id in seen_item_ids:
                continue
            seen_item_ids.add(extra.item_id)
            doc_id = autentique_ids_in_controle_link(extra.signature_link)[-1]
            rows.append(
                ErroneousSyncItemRow(
                    item_id=extra.item_id,
                    item_name=extra.name,
                    item_status=extra.status,
                    autentique_document_id=doc_id,
                    legacy_assinado_item_id=keeper.item_id,
                    legacy_assinado_item_name=keeper.name,
                    reason="duplicate_pending_same_title_signed_doc",
                ),
            )


def find_erroneous_sync_duplicate_items(
    *,
    index: ControleAssinaturasIndex,
    documents_by_id: dict[str, AutentiqueDocumentSummary],
    autentique_api_token: str | None = None,
) -> tuple[ErroneousSyncItemRow, ...]:
    """Itens em fila pendente, ainda Aguardando, com doc assinado e par Assinado legado."""
    rows: list[ErroneousSyncItemRow] = []
    seen_item_ids: set[str] = set()
    pending_ids = {p.item_id for p in index.pending_track_items}
    for item in index.all_items:
        if item.item_id not in pending_ids:
            continue
        if not _status_is_pending_sync_noise(item.status):
            continue
        linked_ids = autentique_ids_in_controle_link(item.signature_link)
        if not linked_ids:
            continue
        primary_doc_id = linked_ids[-1]
        if not _document_fully_signed(
            primary_doc_id,
            documents_by_id=documents_by_id,
            autentique_api_token=autentique_api_token,
        ):
            continue
        legacy_hits = list(
            find_legacy_signed_name_matches(document_name=item.name, items=index.all_items),
        )
        if not legacy_hits:
            continue
        legacy = legacy_hits[0]
        seen_item_ids.add(item.item_id)
        rows.append(
            ErroneousSyncItemRow(
                item_id=item.item_id,
                item_name=item.name,
                item_status=item.status,
                autentique_document_id=primary_doc_id,
                legacy_assinado_item_id=legacy.item_id,
                legacy_assinado_item_name=legacy.name,
                reason="fully_signed_doc_pending_duplicate_of_legacy_assinado",
            ),
        )
    _append_duplicate_normalized_name_candidates(
        index=index,
        documents_by_id=documents_by_id,
        autentique_api_token=autentique_api_token,
        pending_ids=pending_ids,
        seen_item_ids=seen_item_ids,
        rows=rows,
    )
    _append_pending_only_duplicate_candidates(
        index=index,
        documents_by_id=documents_by_id,
        autentique_api_token=autentique_api_token,
        pending_ids=pending_ids,
        seen_item_ids=seen_item_ids,
        rows=rows,
    )
    return tuple(rows)


def remediate_erroneous_sync_duplicates(
    *,
    monday_api_token: str,
    autentique_api_token: str | None = None,
    max_pages: int = 50,
    dry_run: bool = True,
) -> ErroneousSyncRemediationResult:
    require_controle_write_unless_dry_run(dry_run=dry_run)
    try:
        documents = list_documents(api_token=autentique_api_token, max_pages=max_pages)
    except AutentiqueClientError as exc:
        raise ValueError(str(exc)) from exc
    documents_by_id = {
        document.document_id.casefold().strip(): document for document in documents
    }
    index = build_controle_assinaturas_index(api_token=monday_api_token)
    candidates = find_erroneous_sync_duplicate_items(
        index=index,
        documents_by_id=documents_by_id,
        autentique_api_token=autentique_api_token,
    )
    archived = 0
    failed = 0
    if dry_run:
        return ErroneousSyncRemediationResult(
            dry_run=True,
            candidates=candidates,
            archived=0,
            failed=0,
        )
    for row in candidates:
        try:
            archive_controle_item(api_token=monday_api_token, item_id=row.item_id)
            archived += 1
        except Exception:
            failed += 1
    return ErroneousSyncRemediationResult(
        dry_run=False,
        candidates=candidates,
        archived=archived,
        failed=failed,
    )
