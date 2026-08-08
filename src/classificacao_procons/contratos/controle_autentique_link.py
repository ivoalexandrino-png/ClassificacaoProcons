"""Autentique ID canônico no link do Controle (evita vários IDs no mesmo item)."""

from __future__ import annotations

import re

from classificacao_procons.contratos.autentique.client import AutentiqueDocumentSummary
from classificacao_procons.contratos.controle_dedup import (
    controle_names_likely_same_contract,
    controle_title_kind_conflict,
    normalized_controle_titles_equal,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem

_CONTROLE_TRACK_LINE = re.compile(r"^controle_track:\s*(jan|luciano)\s*$", re.IGNORECASE)
_ASSINA_LINK = re.compile(r"https?://assina\.ae/\S+", re.IGNORECASE)


def extract_autentique_document_ids_from_text(text: str) -> set[str]:
    normalized = text.casefold()
    tokens: set[str] = set()
    for match in re.findall(r"[a-f0-9]{32,64}", normalized):
        tokens.add(match)
    if "autentique id:" in normalized:
        tail = normalized.split("autentique id:", maxsplit=1)[1].strip()
        first_line = tail.splitlines()[0].strip()
        if first_line:
            tokens.add(first_line)
    return tokens


def autentique_ids_in_controle_link(text: str | None) -> tuple[str, ...]:
    """IDs hex do Autentique presentes no campo de link (ordem estável)."""
    if not text:
        return ()
    return tuple(sorted(extract_autentique_document_ids_from_text(text)))


def pick_primary_autentique_document_id(
    *,
    item_name: str,
    linked_ids: tuple[str, ...] | set[str] | frozenset[str],
    documents_by_id: dict[str, AutentiqueDocumentSummary],
) -> str | None:
    """Escolhe um único documento Autentique para reconciliar com o item Monday."""
    ids = tuple(sorted(linked_ids))
    if not ids:
        return None
    if len(ids) == 1:
        return ids[0]

    exact: list[str] = []
    fuzzy: list[str] = []
    for doc_id in ids:
        document = documents_by_id.get(doc_id)
        if document is None:
            continue
        if controle_title_kind_conflict(document.name, item_name):
            continue
        if normalized_controle_titles_equal(document.name, item_name):
            exact.append(doc_id)
        elif controle_names_likely_same_contract(document.name, item_name):
            fuzzy.append(doc_id)

    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return exact[0]
    if len(fuzzy) == 1:
        return fuzzy[0]

    known = [i for i in ids if i in documents_by_id]
    if len(known) == 1:
        return known[0]
    return ids[0]


def pick_primary_autentique_document_id_for_item(
    item: ControleAssinaturasItem,
    *,
    documents_by_id: dict[str, AutentiqueDocumentSummary],
) -> str | None:
    return pick_primary_autentique_document_id(
        item_name=item.name,
        linked_ids=autentique_ids_in_controle_link(item.signature_link),
        documents_by_id=documents_by_id,
    )


def rebuild_controle_signature_link_text(
    *,
    previous_link: str | None,
    document_id: str,
    short_link: str | None = None,
) -> str:
    """Monta link com no máximo um ``Autentique ID`` (preserva assina.ae e controle_track)."""
    lines: list[str] = []
    for raw in (previous_link or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.casefold().startswith("autentique id:"):
            continue
        line_ids = extract_autentique_document_ids_from_text(line)
        if line_ids and "autentique id:" not in line.casefold():
            if re.fullmatch(r"[a-f0-9]{32,64}", line, flags=re.IGNORECASE):
                continue
        lines.append(line)

    assina = short_link
    if not assina:
        for line in lines:
            match = _ASSINA_LINK.search(line)
            if match:
                assina = match.group(0)
                break
    if assina and not any(_ASSINA_LINK.search(part) for part in lines):
        lines.insert(0, assina)

    track_lines = [ln for ln in lines if _CONTROLE_TRACK_LINE.match(ln)]
    body = [ln for ln in lines if ln not in track_lines]
    body.append(f"Autentique ID: {document_id.strip()}")
    body.extend(track_lines)
    return "\n".join(body)
