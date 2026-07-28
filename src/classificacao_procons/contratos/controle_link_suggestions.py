"""Sugestões e vínculo automático legado Monday ↔ Autentique."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from classificacao_procons.contratos.autentique.client import (
    AutentiqueClientError,
    AutentiqueDocumentSummary,
    list_documents,
)
from classificacao_procons.contratos.controle_dedup import (
    controle_names_likely_same_contract,
    normalized_controle_titles_equal,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex
from classificacao_procons.monday.client import MondayClientError


@dataclass(frozen=True)
class ControleLinkSuggestion:
    monday_item_id: str
    monday_item_name: str
    monday_status: str | None
    autentique_document_id: str
    autentique_document_name: str
    match_reason: str
    confidence: str  # "high" | "medium"
    autentique_fully_signed: bool


def _item_has_autentique_link(
    item: ControleAssinaturasItem,
    index: ControleAssinaturasIndex,
) -> bool:
    for doc_id, indexed_item in index.items_by_document_id:
        if indexed_item.item_id == item.item_id:
            return True
    link = (item.signature_link or "").casefold()
    return "autentique id:" in link


def _score_pair(
    *,
    monday_name: str,
    autentique_name: str,
) -> tuple[int, str] | None:
    if normalized_controle_titles_equal(monday_name, autentique_name):
        return 100, "exact_title"
    if controle_names_likely_same_contract(autentique_name, monday_name):
        return 80, "strong_title_match"
    return None


def suggest_legacy_controle_links(
    *,
    index: ControleAssinaturasIndex,
    pending_documents: tuple[AutentiqueDocumentSummary, ...] | list[AutentiqueDocumentSummary],
    covered_document_ids: frozenset[str] | None = None,
) -> tuple[ControleLinkSuggestion, ...]:
    """Sugere vínculos só para itens Monday sem ID e docs Autentique ainda não cobertos.

    Não grava no Monday. Múltiplas sugestões para o mesmo item = revisão manual.
    """
    del covered_document_ids

    legacy_items = tuple(
        item for item in index.all_items if not _item_has_autentique_link(item, index)
    )

    suggestions: list[ControleLinkSuggestion] = []
    for item in legacy_items:
        for document in pending_documents:
            if index.get_item(document.document_id) is not None:
                continue
            scored = _score_pair(monday_name=item.name, autentique_name=document.name)
            if scored is None:
                continue
            score, reason = scored
            confidence = "high" if score >= 100 else "medium"
            suggestions.append(
                ControleLinkSuggestion(
                    monday_item_id=item.item_id,
                    monday_item_name=item.name,
                    monday_status=item.status,
                    autentique_document_id=document.document_id,
                    autentique_document_name=document.name,
                    match_reason=reason,
                    confidence=confidence,
                    autentique_fully_signed=document.is_fully_signed,
                ),
            )

    suggestions.sort(
        key=lambda row: (
            row.monday_item_id,
            0 if row.confidence == "high" else 1,
            row.autentique_document_name,
        ),
    )
    return tuple(suggestions)


@dataclass(frozen=True)
class LegacyAutoLinkItemResult:
    monday_item_id: str
    autentique_document_id: str
    autentique_document_name: str
    action: str  # linked | would_link | failed
    linked_item_ids: tuple[str, ...] = ()
    detail: str | None = None


@dataclass(frozen=True)
class LegacyAutoLinkResult:
    applied: int
    would_apply: int
    ambiguous_skipped: int
    failed: int
    dry_run: bool
    items: tuple[LegacyAutoLinkItemResult, ...]


def filter_unambiguous_auto_legacy_links(
    suggestions: tuple[ControleLinkSuggestion, ...] | list[ControleLinkSuggestion],
) -> tuple[ControleLinkSuggestion, ...]:
    """Somente título exato (alta confiança) e par único item Monday ↔ documento."""
    exact_high = tuple(
        row
        for row in suggestions
        if row.confidence == "high" and row.match_reason == "exact_title"
    )
    if not exact_high:
        return ()

    by_item = Counter(row.monday_item_id for row in exact_high)
    by_doc = Counter(row.autentique_document_id.casefold().strip() for row in exact_high)
    return tuple(
        row
        for row in exact_high
        if by_item[row.monday_item_id] == 1
        and by_doc[row.autentique_document_id.casefold().strip()] == 1
    )


def auto_link_unambiguous_legacy_controle(
    *,
    api_token: str,
    autentique_api_token: str | None = None,
    max_pages: int = 50,
    dry_run: bool = False,
    index: ControleAssinaturasIndex | None = None,
    pending_documents: tuple[AutentiqueDocumentSummary, ...] | None = None,
) -> LegacyAutoLinkResult:
    """Grava Autentique ID em itens legados quando o match é inequívoco (título exato)."""
    from classificacao_procons.contratos.monday_contracts import build_controle_assinaturas_index

    if index is None or pending_documents is None:
        try:
            documents = list_documents(api_token=autentique_api_token, max_pages=max_pages)
        except AutentiqueClientError as exc:
            raise ValueError(str(exc)) from exc
        index = build_controle_assinaturas_index(api_token=api_token)
        pending_documents = tuple(
            document
            for document in documents
            if not document.is_fully_signed and index.get_item(document.document_id) is None
        )

    suggestions = suggest_legacy_controle_links(
        index=index,
        pending_documents=pending_documents,
    )
    exact_high_count = sum(
        1
        for row in suggestions
        if row.confidence == "high" and row.match_reason == "exact_title"
    )
    to_apply = filter_unambiguous_auto_legacy_links(suggestions)
    ambiguous_skipped = exact_high_count - len(to_apply)

    items: list[LegacyAutoLinkItemResult] = []
    applied = 0
    would_apply = 0
    failed = 0

    for suggestion in to_apply:
        if dry_run:
            would_apply += 1
            items.append(
                LegacyAutoLinkItemResult(
                    monday_item_id=suggestion.monday_item_id,
                    autentique_document_id=suggestion.autentique_document_id,
                    autentique_document_name=suggestion.autentique_document_name,
                    action="would_link",
                ),
            )
            continue
        try:
            linked = apply_controle_link_suggestion(
                api_token=api_token,
                monday_item_id=suggestion.monday_item_id,
                document_id=suggestion.autentique_document_id,
                index=index,
            )
            applied += 1
            items.append(
                LegacyAutoLinkItemResult(
                    monday_item_id=suggestion.monday_item_id,
                    autentique_document_id=suggestion.autentique_document_id,
                    autentique_document_name=suggestion.autentique_document_name,
                    action="linked",
                    linked_item_ids=linked,
                ),
            )
            index = build_controle_assinaturas_index(api_token=api_token)
        except (ValueError, MondayClientError) as exc:
            failed += 1
            items.append(
                LegacyAutoLinkItemResult(
                    monday_item_id=suggestion.monday_item_id,
                    autentique_document_id=suggestion.autentique_document_id,
                    autentique_document_name=suggestion.autentique_document_name,
                    action="failed",
                    detail=str(exc),
                ),
            )

    return LegacyAutoLinkResult(
        applied=applied,
        would_apply=would_apply,
        ambiguous_skipped=ambiguous_skipped,
        failed=failed,
        dry_run=dry_run,
        items=tuple(items),
    )


def apply_controle_link_suggestion(
    *,
    api_token: str,
    monday_item_id: str,
    document_id: str,
    index: ControleAssinaturasIndex,
) -> tuple[str, ...]:
    """Grava Autentique ID no item Monday (e no espelho Jan/Luciano com o mesmo título)."""
    from classificacao_procons.contratos.monday_contracts import (
        ensure_autentique_id_on_controle_items,
    )

    primary = next((i for i in index.all_items if i.item_id == monday_item_id), None)
    if primary is None:
        raise ValueError(f'Item Monday "{monday_item_id}" não encontrado no índice.')

    to_link = [primary]
    for item in index.all_items:
        if item.item_id == monday_item_id:
            continue
        if _item_has_autentique_link(item, index):
            continue
        if normalized_controle_titles_equal(item.name, primary.name):
            to_link.append(item)

    ensure_autentique_id_on_controle_items(
        api_token=api_token,
        document_id=document_id,
        items=tuple(to_link),
    )
    return tuple(item.item_id for item in to_link)
