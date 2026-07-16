"""Resolução do contrato pai para subitens (aditivos e documentos complementares)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from classificacao_procons.contratos.constants import MONDAY_CONTRATOS_BOARD_ID
from classificacao_procons.contratos.contratos_routing import (
    extract_parent_search_terms,
    score_parent_name_match,
)
from classificacao_procons.contratos.gemini_extractor import ContractMetadata
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.monday.client import _graphql_request

RELATED_CONTRACT_COLUMN_KEYWORDS: tuple[str, ...] = (
    "contrato relacionado",
    "contrato principal",
    "vinculo",
    "vínculo",
    "link contrato",
    "contrato vinculado",
)

CNPJ_COLUMN_KEYWORDS: tuple[str, ...] = ("cnpj",)


@dataclass(frozen=True)
class ContratosBoardItem:
    item_id: str
    name: str
    cnpj: str | None


@dataclass(frozen=True)
class ContratosBoardIndex:
    items: tuple[ContratosBoardItem, ...]
    cnpj_column_id: str | None


@dataclass(frozen=True)
class ParentResolutionResult:
    parent_item_id: str | None
    strategy: str | None


def _normalize_cnpj(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return digits or None


def _parse_linked_item_ids(column_value: str | None) -> list[str]:
    if not column_value:
        return []
    try:
        payload = json.loads(column_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []

    linked_ids: list[str] = []
    for key in ("linkedPulseIds", "linked_pulse_ids", "item_ids"):
        raw = payload.get(key)
        if isinstance(raw, list):
            linked_ids.extend(str(item_id) for item_id in raw if item_id)

    linked_items = payload.get("linkedItems")
    if isinstance(linked_items, list):
        for item in linked_items:
            if isinstance(item, dict) and item.get("id"):
                linked_ids.append(str(item["id"]))

    return linked_ids


def _discover_column_id(
    *,
    api_token: str,
    board_id: str,
    title_keywords: tuple[str, ...],
    allowed_types: tuple[str, ...] | None = None,
) -> str | None:
    data = _graphql_request(
        api_token=api_token,
        query="""
        query ($boardId: [ID!]) {
          boards(ids: $boardId) {
            columns { id title type }
          }
        }
        """,
        variables={"boardId": board_id},
    )
    boards = data.get("boards", [])
    if not boards:
        return None

    for column in boards[0].get("columns", []):
        title = str(column.get("title", "")).casefold()
        column_type = str(column.get("type", ""))
        if allowed_types and column_type not in allowed_types:
            continue
        if any(keyword in title for keyword in title_keywords):
            return str(column["id"])
    return None


def load_contratos_board_index(*, api_token: str) -> ContratosBoardIndex:
    """Carrega índice do quadro Contratos (nome + CNPJ) para match do pai."""
    cnpj_column_id = _discover_column_id(
        api_token=api_token,
        board_id=MONDAY_CONTRATOS_BOARD_ID,
        title_keywords=CNPJ_COLUMN_KEYWORDS,
        allowed_types=("text", "long_text", "numbers"),
    )
    column_ids = [cnpj_column_id] if cnpj_column_id else []

    items: list[ContratosBoardItem] = []
    cursor: str | None = None
    for _ in range(50):
        data = _graphql_request(
            api_token=api_token,
            query="""
            query ($boardId: ID!, $limit: Int!, $cursor: String, $columnIds: [String!]) {
              boards(ids: [$boardId]) {
                items_page(limit: $limit, cursor: $cursor) {
                  cursor
                  items {
                    id
                    name
                    column_values(ids: $columnIds) {
                      id
                      text
                    }
                  }
                }
              }
            }
            """,
            variables={
                "boardId": MONDAY_CONTRATOS_BOARD_ID,
                "limit": 100,
                "cursor": cursor,
                "columnIds": column_ids,
            },
        )
        page = data["boards"][0]["items_page"]
        for item in page["items"]:
            cnpj_value = None
            for column in item.get("column_values", []):
                if cnpj_column_id and column.get("id") == cnpj_column_id:
                    cnpj_value = column.get("text")
            items.append(
                ContratosBoardItem(
                    item_id=str(item["id"]),
                    name=str(item.get("name", "")),
                    cnpj=_normalize_cnpj(str(cnpj_value) if cnpj_value else None),
                )
            )
        cursor = page.get("cursor")
        if not cursor:
            break

    return ContratosBoardIndex(items=tuple(items), cnpj_column_id=cnpj_column_id)


def discover_controle_related_contract_column_id(*, api_token: str) -> str | None:
    """Descobre coluna de vínculo com contrato no Controle Assinaturas."""
    from classificacao_procons.contratos.constants import MONDAY_CONTROLE_ASSINATURAS_BOARD_ID

    return _discover_column_id(
        api_token=api_token,
        board_id=MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
        title_keywords=RELATED_CONTRACT_COLUMN_KEYWORDS,
        allowed_types=("board_relation", "connect_boards", "link"),
    )


def _resolve_from_controle_link(
    *,
    controle_item: ControleAssinaturasItem | None,
    board_index: ContratosBoardIndex,
) -> ParentResolutionResult | None:
    if controle_item is None or not controle_item.related_contract_item_ids:
        return None

    known_ids = {item.item_id for item in board_index.items}
    for linked_id in controle_item.related_contract_item_ids:
        if linked_id in known_ids:
            return ParentResolutionResult(parent_item_id=linked_id, strategy="controle_link")
    if controle_item.related_contract_item_ids:
        return ParentResolutionResult(
            parent_item_id=controle_item.related_contract_item_ids[0],
            strategy="controle_link",
        )
    return None


def _resolve_from_cnpj(
    *,
    metadata: ContractMetadata,
    board_index: ContratosBoardIndex,
) -> ParentResolutionResult | None:
    cnpj = _normalize_cnpj(metadata.parent_contract_cnpj or metadata.counterparty_cnpj)
    if not cnpj:
        return None

    matches = [item for item in board_index.items if item.cnpj and item.cnpj == cnpj]
    if not matches:
        return None
    if len(matches) == 1:
        return ParentResolutionResult(parent_item_id=matches[0].item_id, strategy="cnpj")
    if metadata.parent_contract_reference:
        for item in matches:
            score = score_parent_name_match(
                item_name=item.name,
                search_term=metadata.parent_contract_reference,
            )
            if score >= 70:
                return ParentResolutionResult(parent_item_id=item.item_id, strategy="cnpj_name")
    return None


def _resolve_from_name_terms(
    *,
    document_name: str,
    metadata: ContractMetadata,
    board_index: ContratosBoardIndex,
    min_score: int,
) -> ParentResolutionResult | None:
    terms = list(extract_parent_search_terms(document_name=document_name, metadata=metadata))
    if metadata.parent_contract_reference:
        terms.insert(0, metadata.parent_contract_reference)

    if not terms:
        return None

    best_item_id: str | None = None
    best_score = 0
    for item in board_index.items:
        for term in terms:
            score = score_parent_name_match(item_name=item.name, search_term=term)
            if score > best_score:
                best_score = score
                best_item_id = item.item_id

    if best_item_id is None or best_score < min_score:
        return None
    strategy = "gemini_reference" if metadata.parent_contract_reference else "name_match"
    return ParentResolutionResult(parent_item_id=best_item_id, strategy=strategy)


def resolve_parent_contrato_item(
    *,
    api_token: str,
    document_name: str,
    metadata: ContractMetadata,
    controle_item: ControleAssinaturasItem | None = None,
    board_index: ContratosBoardIndex | None = None,
    min_name_score: int = 70,
) -> ParentResolutionResult:
    """Resolve contrato pai com múltiplas estratégias (link, CNPJ, nome, Gemini)."""
    index = board_index or load_contratos_board_index(api_token=api_token)

    for resolver in (
        lambda: _resolve_from_controle_link(controle_item=controle_item, board_index=index),
        lambda: _resolve_from_cnpj(metadata=metadata, board_index=index),
        lambda: _resolve_from_name_terms(
            document_name=document_name,
            metadata=metadata,
            board_index=index,
            min_score=min_name_score,
        ),
    ):
        result = resolver()
        if result and result.parent_item_id:
            return result

    return ParentResolutionResult(parent_item_id=None, strategy=None)
