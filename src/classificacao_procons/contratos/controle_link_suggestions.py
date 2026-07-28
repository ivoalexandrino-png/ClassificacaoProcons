"""Sugestões de vínculo legado Monday ↔ Autentique (confirmação humana)."""

from __future__ import annotations

from dataclasses import dataclass

from classificacao_procons.contratos.autentique.client import AutentiqueDocumentSummary
from classificacao_procons.contratos.controle_dedup import (
    controle_names_likely_same_contract,
    normalized_controle_titles_equal,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


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
