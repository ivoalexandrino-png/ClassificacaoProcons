"""Evita criar filas novas quando já existe item legado Assinado no Controle."""

from __future__ import annotations

from classificacao_procons.contratos.constants import CONTROLE_STATUS_ASSINADO
from classificacao_procons.contratos.controle_dedup import (
    find_exact_title_matches,
    find_likely_name_matches,
    normalize_controle_title,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem


def status_is_assinado(status: str | None) -> bool:
    if not status:
        return False
    return status.casefold().strip() == CONTROLE_STATUS_ASSINADO.casefold()


def find_legacy_signed_name_matches(
    *,
    document_name: str,
    items: tuple[ControleAssinaturasItem, ...],
) -> tuple[ControleAssinaturasItem, ...]:
    """Itens no Monday já Assinados com título exato ou forte parecido com o Autentique."""
    exact = find_exact_title_matches(document_name=document_name, items=items)
    likely = find_likely_name_matches(document_name=document_name, items=items)
    seen: set[str] = set()
    matched: list[ControleAssinaturasItem] = []
    for item in (*exact, *likely):
        if item.item_id in seen:
            continue
        if not status_is_assinado(item.status):
            continue
        seen.add(item.item_id)
        matched.append(item)
    return tuple(matched)


def should_block_create_for_signed_autentique(
    *,
    document_name: str,
    is_fully_signed: bool,
    items: tuple[ControleAssinaturasItem, ...],
    import_signed_as_new: bool = False,
) -> bool:
    """Bloqueia criação de par Jan/Luciano quando o doc já está assinado e há legado Assinado."""
    if import_signed_as_new or not is_fully_signed:
        return False
    return bool(find_legacy_signed_name_matches(document_name=document_name, items=items))


def normalized_names_collide(a: str, b: str) -> bool:
    left = normalize_controle_title(a)
    right = normalize_controle_title(b)
    return bool(left) and left == right
