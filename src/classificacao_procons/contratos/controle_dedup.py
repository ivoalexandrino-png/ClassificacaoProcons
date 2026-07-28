"""Deduplicação de itens do Controle Assinaturas (nome vs Autentique)."""

from __future__ import annotations

import re
import unicodedata

from classificacao_procons.contratos.models import ControleAssinaturasItem

_NAME_STOPWORDS: frozenset[str] = frozenset(
    {
        "contrato",
        "contratos",
        "minuta",
        "minutas",
        "padrao",
        "padrão",
        "modelo",
        "b2b",
        "b4a",
        "aditivo",
        "distrato",
        "parceria",
        "comercial",
        "fornecimento",
        "prestacao",
        "prestação",
        "servicos",
        "serviços",
        "empresa",
        "termo",
        "acordo",
        "nda",
        "anexo",
        "lab",
    },
)

_DATE_TOKEN = re.compile(r"^\d{1,2}[./]\d{1,2}[./]\d{2,4}$")
_SUFFIX_COPY = re.compile(r"\(\d+\)$")


def _normalize_controle_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    cleaned = _SUFFIX_COPY.sub("", without_marks)
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_controle_name_tokens(document_name: str) -> set[str]:
    """Tokens distintivos do título (contraparte, marca, projeto)."""
    normalized = _normalize_controle_name(document_name)
    raw_parts = re.split(r"[\s\-–—/,]+", normalized)
    tokens: set[str] = set()
    for part in raw_parts:
        token = part.strip()
        if len(token) < 3:
            continue
        if _DATE_TOKEN.match(token):
            continue
        if token in _NAME_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def controle_names_likely_same_contract(
    autentique_name: str,
    monday_item_name: str,
) -> bool:
    """Indica se títulos diferentes referem-se ao mesmo contrato no Controle."""
    left = _normalize_controle_name(autentique_name)
    right = _normalize_controle_name(monday_item_name)
    if not left or not right:
        return False
    if left == right:
        return True
    if left in right or right in left:
        return True

    left_tokens = extract_controle_name_tokens(autentique_name)
    right_tokens = extract_controle_name_tokens(monday_item_name)
    overlap = left_tokens & right_tokens
    if not overlap:
        return False

    distinctive = {token for token in overlap if len(token) >= 5}
    if distinctive:
        return True
    return len(overlap) >= 2


def find_likely_name_matches(
    *,
    document_name: str,
    items: tuple[ControleAssinaturasItem, ...] | list[ControleAssinaturasItem],
) -> tuple[ControleAssinaturasItem, ...]:
    return tuple(
        item
        for item in items
        if controle_names_likely_same_contract(document_name, item.name)
    )
