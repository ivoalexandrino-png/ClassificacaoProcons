"""Análise de duplicatas e divergências Controle ↔ Autentique (somente leitura)."""

from __future__ import annotations

from collections import defaultdict

from classificacao_procons.contratos.autentique.client import AutentiqueDocumentSummary
from classificacao_procons.contratos.constants import CONTROLE_STATUS_ASSINADO
from classificacao_procons.contratos.controle_dedup import normalize_controle_title
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


def find_duplicate_autentique_ids(
    index: ControleAssinaturasIndex,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Mesmo Autentique ID em mais de um item Monday."""
    by_id: dict[str, set[str]] = defaultdict(set)
    for doc_id, item in index.items_by_document_id:
        by_id[doc_id].add(item.item_id)
    return tuple(
        (doc_id, tuple(sorted(item_ids)))
        for doc_id, item_ids in sorted(by_id.items())
        if len(item_ids) > 1
    )


def find_duplicate_normalized_names(
    index: ControleAssinaturasIndex,
) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """Mesmo título normalizado em mais de um item (possível duplicata)."""
    by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for item in index.all_items:
        key = normalize_controle_title(item.name)
        if not key:
            continue
        by_name[key].append((item.item_id, item.name))
    return tuple(
        (normalized, tuple(entries))
        for normalized, entries in sorted(by_name.items())
        if len(entries) > 1
    )


def _status_matches_monday(current: str | None, expected: str) -> bool:
    if not current:
        return False
    return current.casefold().strip() == expected.casefold().strip()


def find_monday_status_behind_autentique(
    *,
    index: ControleAssinaturasIndex,
    documents_by_id: dict[str, AutentiqueDocumentSummary],
) -> tuple[tuple[str, str, str, str | None, str], ...]:
    """Item no Monday ainda pendente enquanto o Autentique já está totalmente assinado."""
    rows: list[tuple[str, str, str, str | None, str]] = []
    seen_items: set[str] = set()
    for doc_id, item in index.items_by_document_id:
        if item.item_id in seen_items:
            continue
        seen_items.add(item.item_id)
        document = documents_by_id.get(doc_id)
        if document is None or not document.is_fully_signed:
            continue
        expected = CONTROLE_STATUS_ASSINADO
        if _status_matches_monday(item.status, expected):
            continue
        rows.append((item.item_id, item.name, doc_id, item.status, expected))
    return tuple(rows)
