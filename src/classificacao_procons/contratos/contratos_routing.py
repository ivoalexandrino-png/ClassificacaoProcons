"""Roteamento Controle Assinaturas → Contratos (automação Monday vs subitem)."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from classificacao_procons.contratos.gemini_extractor import ContractMetadata

ContratosRegistrationMode = Literal["monday_automation", "subitem", "skip"]

SUPPLEMENTAL_DOCUMENT_KEYWORDS: tuple[str, ...] = (
    "aditivo",
    "distrato",
    "termo aditivo",
    "anexo",
    "prorrogacao",
    "prorrogação",
    "renovacao",
    "renovação",
    "resilição",
    "resilicao",
    "carta de autorizacao",
    "carta de autorização",
    "mou",
    "memorando de entendimento",
    "dpa",
    "proposta comercial",
    "proposta ",
)


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


def is_supplemental_document(
    *,
    document_name: str,
    metadata: ContractMetadata | None = None,
) -> bool:
    """Indica documentos complementares (aditivos, distratos etc.) sem Tipo no Controle."""
    if metadata is not None and metadata.is_supplemental is True:
        return True
    if metadata is not None and metadata.is_supplemental is False:
        return False
    blob = _normalize_text(document_name)
    return any(keyword in blob for keyword in SUPPLEMENTAL_DOCUMENT_KEYWORDS)


def resolve_contratos_registration_mode(
    *,
    controle_tipo: str | None,
    controle_item_found: bool,
) -> ContratosRegistrationMode:
    """Define se o Monday move o item, se criamos subitem ou se não há ação.

    A automação nativa do Monday no Controle Assinaturas exige a coluna Tipo
    preenchida para criar o item no quadro Contratos. Sem Tipo, nosso código
    cria um subitem vinculado ao contrato pai.
    """
    if not controle_item_found:
        return "skip"
    if controle_tipo and controle_tipo.strip():
        return "monday_automation"
    return "subitem"


def extract_parent_search_terms(
    *,
    document_name: str,
    metadata: ContractMetadata,
) -> list[str]:
    """Gera termos para localizar o contrato pai no quadro Contratos."""
    terms: list[str] = []
    seen: set[str] = set()

    def add_term(value: str | None) -> None:
        if not value:
            return
        cleaned = " ".join(value.split()).strip()
        if not cleaned:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        terms.append(cleaned)

    add_term(metadata.counterparty_name)
    add_term(metadata.property_name)

    add_term(metadata.parent_contract_reference)

    name_parts = [part.strip() for part in document_name.split(" - ") if part.strip()]
    if len(name_parts) > 1:
        add_term(name_parts[-1])

    stripped_name = re.sub(
        r"^(aditivo|distrato|termo aditivo|anexo|prorroga[cç][aã]o|renova[cç][aã]o)\s+",
        "",
        document_name,
        flags=re.IGNORECASE,
    ).strip()
    if stripped_name and stripped_name.casefold() != document_name.casefold():
        add_term(stripped_name)
        if " - " in stripped_name:
            add_term(stripped_name.split(" - ", maxsplit=1)[-1].strip())

    return terms


def score_parent_name_match(*, item_name: str, search_term: str) -> int:
    """Pontua correspondência entre nome do item pai e termo de busca."""
    normalized_item = _normalize_text(item_name)
    normalized_term = _normalize_text(search_term)
    if not normalized_item or not normalized_term:
        return 0
    if normalized_item == normalized_term:
        return 100
    if normalized_term in normalized_item:
        return 80
    if normalized_item in normalized_term:
        return 70
    item_tokens = {token for token in re.split(r"[\s\-/,]+", normalized_item) if len(token) > 2}
    term_tokens = {token for token in re.split(r"[\s\-/,]+", normalized_term) if len(token) > 2}
    if not item_tokens or not term_tokens:
        return 0
    overlap = len(item_tokens & term_tokens)
    if overlap == 0:
        return 0
    return 40 + overlap * 10
