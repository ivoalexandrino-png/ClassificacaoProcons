"""Integração Monday.com para contratos assinados."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from classificacao_procons.contratos.constants import (
    CONTRATOS_GROUP_BY_TIPO,
    CONTROLE_COL_DATA_ASSINATURA,
    CONTROLE_COL_LINK_ASSINADO,
    CONTROLE_COL_LINK_ASSINATURA,
    CONTROLE_COL_STATUS,
    CONTROLE_COL_TIPO,
    CONTROLE_GROUP_ASSINADOS,
    CONTROLE_LINK_TRACK_JAN,
    CONTROLE_LINK_TRACK_LUCIANO,
    CONTROLE_STATUS_ASSINADO,
    DEFAULT_CONTRATOS_GROUP_ID,
    DYNAMIC_CONTRATOS_GROUP_TITLES,
    MONDAY_CONTRATOS_BOARD_ID,
    MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
)
from classificacao_procons.contratos.controle_autentique_link import (
    autentique_ids_in_controle_link,
    extract_autentique_document_ids_from_text,
    rebuild_controle_signature_link_text,
)
from classificacao_procons.contratos.controle_board_scope import (
    is_controle_pending_track_group_title,
)
from classificacao_procons.contratos.drive_routing import infer_category, infer_monday_tipo
from classificacao_procons.contratos.gemini_extractor import ContractMetadata
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.parent_resolver import (
    discover_controle_related_contract_column_id,
)
from classificacao_procons.monday.client import (
    MondayClientError,
    _graphql_request,
    load_board_metadata,
    upload_file_to_column,
)
from classificacao_procons.monday.mapping import (
    MondayColumn,
    format_column_value,
    format_link_column_value,
)


@dataclass(frozen=True)
class MondayColumnDetails:
    column: MondayColumn
    settings_str: str | None = None


@dataclass(frozen=True)
class MondayContractRegistrationResult:
    controle_item_id: str | None
    contratos_item_id: str | None
    contratos_item_url: str | None
    skipped_duplicate: bool = False
    registration_mode: str | None = None
    parent_item_id: str | None = None


def is_controle_contratos_trigger_item(item: ControleAssinaturasItem) -> bool:
    """Item cuja coluna Tipo dispara a automação Monday → Contratos (fila Jan)."""
    if item.tipo and str(item.tipo).strip():
        return True
    link = item.signature_link or ""
    return CONTROLE_LINK_TRACK_JAN.casefold() in link.casefold()


def infer_controle_signer_track(item: ControleAssinaturasItem) -> str:
    """Retorna ``jan``, ``luciano`` ou ``unknown`` a partir do link de assinatura."""
    link = (item.signature_link or "").casefold()
    if CONTROLE_LINK_TRACK_LUCIANO.casefold() in link:
        return "luciano"
    if CONTROLE_LINK_TRACK_JAN.casefold() in link:
        return "jan"
    if is_controle_contratos_trigger_item(item):
        return "jan"
    return "unknown"


def pick_canonical_controle_item(
    items: tuple[ControleAssinaturasItem, ...] | list[ControleAssinaturasItem],
) -> ControleAssinaturasItem | None:
    """Escolhe o item gatilho (Tipo / fila Jan) entre duplicatas do mesmo Autentique ID."""
    if not items:
        return None
    for item in items:
        if is_controle_contratos_trigger_item(item):
            return item
    return items[0]


def find_controle_items_by_autentique_id(
    *,
    api_token: str,
    document_id: str,
) -> tuple[ControleAssinaturasItem, ...]:
    """Todos os itens do Controle vinculados ao mesmo documento Autentique."""
    normalized_id = document_id.casefold().strip()
    if not normalized_id:
        return ()

    related_col_id = discover_controle_related_contract_column_id(api_token=api_token)
    column_ids = ["status", "status_1__1", "long_text_mkvnwp6d"]
    if related_col_id:
        column_ids.append(related_col_id)

    matches: list[ControleAssinaturasItem] = []
    cursor: str | None = None
    for _ in range(30):
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
                    group { id }
                    column_values(ids: $columnIds) {
                      id
                      text
                      value
                    }
                  }
                }
              }
            }
            """,
            variables={
                "boardId": MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
                "limit": 100,
                "cursor": cursor,
                "columnIds": column_ids,
            },
        )
        page = data["boards"][0]["items_page"]
        for item in page["items"]:
            columns_by_id = {
                column["id"]: column for column in item.get("column_values", [])
            }
            values = {column_id: column.get("text") for column_id, column in columns_by_id.items()}
            signature_link = values.get(CONTROLE_COL_LINK_ASSINATURA) or ""
            if normalized_id not in signature_link.casefold():
                continue
            item["group"] = item.get("group") or {}
            matches.append(
                _to_controle_item(
                    item,
                    values,
                    signature_link,
                    related_col_id=related_col_id,
                    columns_by_id=columns_by_id,
                ),
            )

        cursor = page.get("cursor")
        if not cursor:
            break

    return tuple(matches)


def find_controle_item(
    *,
    api_token: str,
    document_id: str,
    document_name: str,
) -> ControleAssinaturasItem | None:
    """Localiza item gatilho no Controle Assinaturas por ID/nome/link Autentique."""
    by_id = find_controle_items_by_autentique_id(api_token=api_token, document_id=document_id)
    if by_id:
        return pick_canonical_controle_item(by_id)
    related_col_id = discover_controle_related_contract_column_id(api_token=api_token)
    column_ids = ["status", "status_1__1", "long_text_mkvnwp6d"]
    if related_col_id:
        column_ids.append(related_col_id)

    cursor: str | None = None
    normalized_name = document_name.casefold().strip()
    normalized_id = document_id.casefold().strip()

    for _ in range(30):
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
                      value
                    }
                  }
                }
              }
            }
            """,
            variables={
                "boardId": MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
                "limit": 100,
                "cursor": cursor,
                "columnIds": column_ids,
            },
        )
        page = data["boards"][0]["items_page"]
        for item in page["items"]:
            columns_by_id = {
                column["id"]: column for column in item.get("column_values", [])
            }
            values = {column_id: column.get("text") for column_id, column in columns_by_id.items()}
            signature_link = values.get(CONTROLE_COL_LINK_ASSINATURA) or ""
            item_name = str(item.get("name", ""))
            if normalized_id and normalized_id in signature_link.casefold():
                return _to_controle_item(
                    item,
                    values,
                    signature_link,
                    related_col_id=related_col_id,
                    columns_by_id=columns_by_id,
                )
            if normalized_name and normalized_name == item_name.casefold().strip():
                return _to_controle_item(
                    item,
                    values,
                    signature_link,
                    related_col_id=related_col_id,
                    columns_by_id=columns_by_id,
                )
            if normalized_name and normalized_name in item_name.casefold():
                return _to_controle_item(
                    item,
                    values,
                    signature_link,
                    related_col_id=related_col_id,
                    columns_by_id=columns_by_id,
                )

        cursor = page.get("cursor")
        if not cursor:
            break

    return None


def find_controle_item_by_autentique_id(
    *,
    api_token: str,
    document_id: str,
) -> ControleAssinaturasItem | None:
    """Localiza item gatilho no Controle Assinaturas pelo ID do Autentique."""
    items = find_controle_items_by_autentique_id(api_token=api_token, document_id=document_id)
    return pick_canonical_controle_item(items)


@dataclass(frozen=True)
class ControleAssinaturasIndex:
    document_ids: frozenset[str]
    exact_names: frozenset[str]
    items_by_document_id: tuple[tuple[str, ControleAssinaturasItem], ...] = ()
    all_items: tuple[ControleAssinaturasItem, ...] = ()
    pending_track_items: tuple[ControleAssinaturasItem, ...] = ()

    def _items_for_title_match(self) -> tuple[ControleAssinaturasItem, ...]:
        if self.pending_track_items:
            return self.pending_track_items
        return self.all_items

    def get_item(self, document_id: str) -> ControleAssinaturasItem | None:
        target = document_id.casefold().strip()
        for indexed_id, item in self.items_by_document_id:
            if indexed_id == target:
                return item
        return None

    def items_for_document_id(self, document_id: str) -> tuple[ControleAssinaturasItem, ...]:
        """Todos os itens Monday (Jan/Luciano) vinculados ao mesmo Autentique ID."""
        target = document_id.casefold().strip()
        if not target:
            return ()
        by_item_id: dict[str, ControleAssinaturasItem] = {}
        for indexed_id, item in self.items_by_document_id:
            if indexed_id != target:
                continue
            by_item_id[item.item_id] = item
        return tuple(by_item_id.values())

    def matches_document(self, document: object) -> bool:
        """Verifica se o documento já está representado no Controle (ID ou nome)."""
        document_id = str(getattr(document, "document_id", "")).casefold().strip()
        if document_id and document_id in self.document_ids:
            return True
        signature_link = str(getattr(document, "primary_signature_link", lambda: None)() or "")
        if document_id and document_id in signature_link.casefold():
            return True

        document_name = str(getattr(document, "name", "")).strip()
        if not document_name:
            return False
        normalized_name = document_name.casefold().strip()
        name_pool = self._items_for_title_match()
        name_exact_names = frozenset(
            item.name.casefold().strip() for item in name_pool if item.name
        )
        if normalized_name in name_exact_names:
            return True
        from classificacao_procons.contratos.controle_dedup import normalized_controle_titles_equal

        for item in name_pool:
            if normalized_controle_titles_equal(document_name, item.name):
                return True
        return False

    def with_item(
        self,
        *,
        document_id: str,
        document_name: str,
        signature_link: str | None,
    ) -> ControleAssinaturasIndex:
        ids = set(self.document_ids)
        names = set(self.exact_names)
        normalized_id = document_id.casefold().strip()
        normalized_name = document_name.casefold().strip()
        if normalized_id:
            ids.add(normalized_id)
        if normalized_name:
            names.add(normalized_name)
        if signature_link:
            for token in _extract_document_ids_from_text(signature_link):
                ids.add(token)
        return ControleAssinaturasIndex(
            document_ids=frozenset(ids),
            exact_names=frozenset(names),
        )


def build_controle_assinaturas_index(*, api_token: str) -> ControleAssinaturasIndex:
    """Indexa documentos já presentes no Controle Assinaturas."""
    document_ids: set[str] = set()
    exact_names: set[str] = set()
    items_by_document_id: dict[str, ControleAssinaturasItem] = {}
    all_items_by_id: dict[str, ControleAssinaturasItem] = {}
    pending_track_by_id: dict[str, ControleAssinaturasItem] = {}
    cursor: str | None = None

    for _ in range(50):
        data = _graphql_request(
            api_token=api_token,
            query="""
            query ($boardId: ID!, $limit: Int!, $cursor: String) {
              boards(ids: [$boardId]) {
                items_page(limit: $limit, cursor: $cursor) {
                  cursor
                  items {
                    id
                    name
                    group { id title }
                    column_values(ids: ["status", "status_1__1", "long_text_mkvnwp6d"]) {
                      id
                      text
                      value
                    }
                  }
                }
              }
            }
            """,
            variables={
                "boardId": MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
                "limit": 100,
                "cursor": cursor,
            },
        )
        page = data["boards"][0]["items_page"]
        for item in page["items"]:
            item_name = str(item.get("name", "")).casefold().strip()
            if item_name:
                exact_names.add(item_name)
            columns_by_id = {
                column["id"]: column for column in item.get("column_values", [])
            }
            values = {column_id: column.get("text") for column_id, column in columns_by_id.items()}
            signature_link = values.get(CONTROLE_COL_LINK_ASSINATURA) or ""
            group = item.get("group") or {}
            group_title = str(group.get("title") or "")
            controle_item = ControleAssinaturasItem(
                item_id=str(item["id"]),
                name=str(item.get("name", "")),
                status=values.get(CONTROLE_COL_STATUS),
                tipo=values.get(CONTROLE_COL_TIPO),
                signature_link=signature_link or None,
                group_id=str(group.get("id")) if group.get("id") else None,
            )
            linked_ids: set[str] = set()
            for column in item.get("column_values", []):
                text = str(column.get("text") or "")
                value = str(column.get("value") or "")
                for token in _extract_document_ids_from_text(f"{text}\n{value}"):
                    document_ids.add(token)
                    linked_ids.add(token)
            for token in linked_ids:
                existing = items_by_document_id.get(token)
                if existing is None or _prefer_controle_index_item(controle_item, existing):
                    items_by_document_id[token] = controle_item
            all_items_by_id[controle_item.item_id] = controle_item
            if is_controle_pending_track_group_title(group_title):
                pending_track_by_id[controle_item.item_id] = controle_item

        cursor = page.get("cursor")
        if not cursor:
            break

    return ControleAssinaturasIndex(
        document_ids=frozenset(document_ids),
        exact_names=frozenset(exact_names),
        items_by_document_id=tuple(items_by_document_id.items()),
        all_items=tuple(all_items_by_id.values()),
        pending_track_items=tuple(pending_track_by_id.values()),
    )


def load_controle_board_groups(*, api_token: str) -> dict[str, str]:
    """Retorna grupos do Controle Assinaturas: título normalizado → id."""
    data = _graphql_request(
        api_token=api_token,
        query="""
        query ($boardId: [ID!]) {
          boards(ids: $boardId) {
            groups { id title }
          }
        }
        """,
        variables={"boardId": MONDAY_CONTROLE_ASSINATURAS_BOARD_ID},
    )
    boards = data.get("boards", [])
    if not boards:
        return {CONTROLE_GROUP_ASSINADOS: CONTROLE_GROUP_ASSINADOS}

    groups: dict[str, str] = {}
    for group in boards[0].get("groups", []):
        title = _normalize_group_title(str(group.get("title", "")))
        groups[title] = str(group["id"])
        if title == "assinados":
            groups[CONTROLE_GROUP_ASSINADOS] = str(group["id"])
    return groups


def create_controle_assinatura_item(
    *,
    api_token: str,
    item_name: str,
    group_id: str,
    signature_link_text: str,
    status_label: str,
    tipo_label: str | None = None,
    signed_at: date | None = None,
    signed_pdf_url: str | None = None,
    signer_label: str | None = None,
    platform_name: str | None = None,
    inclusion_date: date | None = None,
) -> tuple[str, str | None]:
    """Cria item no Controle Assinaturas."""
    board_context = load_board_metadata(
        api_token=api_token,
        board_id=MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
    )
    column_details = _load_controle_column_details(api_token=api_token)
    column_values = _sanitize_column_values(
        column_details,
        _build_controle_column_values(
            [detail.column for detail in column_details],
            signature_link_text=signature_link_text,
            status_label=status_label,
            tipo_label=tipo_label,
            signed_at=signed_at,
            signed_pdf_url=signed_pdf_url,
            signer_label=signer_label,
            platform_name=platform_name,
            inclusion_date=inclusion_date,
        ),
    )

    item_id = _create_controle_item(
        api_token=api_token,
        group_id=group_id,
        item_name=item_name,
        column_values={},
    )
    _apply_controle_column_values(
        api_token=api_token,
        item_id=item_id,
        column_details=column_details,
        column_values=column_values,
    )

    item_url = None
    if board_context.account_slug:
        item_url = (
            f"https://{board_context.account_slug}.monday.com/boards/"
            f"{MONDAY_CONTROLE_ASSINATURAS_BOARD_ID}/pulses/{item_id}"
        )
    return item_id, item_url


def _load_controle_column_details(*, api_token: str) -> list[MondayColumnDetails]:
    data = _graphql_request(
        api_token=api_token,
        query="""
        query ($boardId: [ID!]) {
          boards(ids: $boardId) {
            columns {
              id
              title
              type
              settings_str
            }
          }
        }
        """,
        variables={"boardId": MONDAY_CONTROLE_ASSINATURAS_BOARD_ID},
    )
    boards = data.get("boards", [])
    if not boards:
        return []
    return [
        MondayColumnDetails(
            column=MondayColumn(
                id=str(column["id"]),
                title=str(column.get("title", "")),
                column_type=str(column.get("type", "")),
            ),
            settings_str=column.get("settings_str"),
        )
        for column in boards[0].get("columns", [])
    ]


def _build_controle_column_values(
    columns: list[MondayColumn],
    *,
    signature_link_text: str,
    status_label: str,
    tipo_label: str | None,
    signed_at: date | None,
    signed_pdf_url: str | None,
    signer_label: str | None = None,
    platform_name: str | None = None,
    inclusion_date: date | None = None,
) -> dict[str, Any]:
    column_by_title = {column.title.casefold(): column for column in columns}
    values: dict[str, Any] = {}

    status_col = columns_by_id_or_title(column_by_title, CONTROLE_COL_STATUS, ("status",))
    if status_col:
        values[status_col.id] = format_column_value(status_col.column_type, status_label)

    link_col = columns_by_id_or_title(
        column_by_title,
        CONTROLE_COL_LINK_ASSINATURA,
        ("link autentique", "assinatura", "link"),
    )
    if link_col:
        values[link_col.id] = format_column_value(link_col.column_type, signature_link_text)

    tipo_col = columns_by_id_or_title(column_by_title, CONTROLE_COL_TIPO, ("tipo",))
    if tipo_col and tipo_label:
        values[tipo_col.id] = format_column_value(tipo_col.column_type, tipo_label)

    data_col = columns_by_id_or_title(column_by_title, CONTROLE_COL_DATA_ASSINATURA, ("data",))
    if data_col and signed_at:
        values[data_col.id] = format_column_value(data_col.column_type, signed_at)

    assinado_col = columns_by_id_or_title(
        column_by_title,
        CONTROLE_COL_LINK_ASSINADO,
        ("contrato assinado", "pdf assinado"),
    )
    if assinado_col and signed_pdf_url:
        values[assinado_col.id] = format_column_value(
            assinado_col.column_type,
            signed_pdf_url,
            link_text="Contrato assinado",
        )

    quem_col = _find_column(column_by_title, ("quem assina",))
    if quem_col and signer_label:
        values[quem_col.id] = format_column_value(quem_col.column_type, signer_label)

    platform_col = _find_column(
        column_by_title,
        ("nome da plataforma", "plataforma"),
    )
    if platform_col and platform_name:
        values[platform_col.id] = format_column_value(platform_col.column_type, platform_name)

    inclusion_col = _find_column(
        column_by_title,
        ("data de inclusao", "inclusão na plataforma", "inclusao"),
    )
    if inclusion_col and inclusion_date:
        values[inclusion_col.id] = format_column_value(inclusion_col.column_type, inclusion_date)

    return {key: value for key, value in values.items() if value is not None}


def columns_by_id_or_title(
    column_by_title: dict[str, MondayColumn],
    column_id: str,
    title_keywords: tuple[str, ...],
) -> MondayColumn | None:
    for column in column_by_title.values():
        if column.id == column_id:
            return column
    return _find_column(column_by_title, title_keywords)


def _apply_controle_column_values(
    *,
    api_token: str,
    item_id: str,
    column_details: list[MondayColumnDetails],
    column_values: dict[str, Any],
) -> None:
    details_by_id = {detail.column.id: detail for detail in column_details}
    for column_id, value in column_values.items():
        if details_by_id.get(column_id) is None:
            continue
        try:
            _graphql_request(
                api_token=api_token,
                query="""
                mutation ($boardId: ID!, $itemId: ID!, $columnValues: JSON!) {
                  change_multiple_column_values(
                    board_id: $boardId
                    item_id: $itemId
                    column_values: $columnValues
                  ) { id }
                }
                """,
                variables={
                    "boardId": MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
                    "itemId": item_id,
                    "columnValues": json.dumps({column_id: value}),
                },
            )
        except MondayClientError:
            continue


def _create_controle_item(
    *,
    api_token: str,
    group_id: str,
    item_name: str,
    column_values: dict[str, Any],
) -> str:
    data = _graphql_request(
        api_token=api_token,
        query="""
        mutation ($boardId: ID!, $groupId: String!, $itemName: String!, $columnValues: JSON) {
          create_item(
            board_id: $boardId
            group_id: $groupId
            item_name: $itemName
            column_values: $columnValues
          ) { id }
        }
        """,
        variables={
            "boardId": MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
            "groupId": group_id,
            "itemName": item_name,
            "columnValues": json.dumps(column_values) if column_values else None,
        },
    )
    return str(data["create_item"]["id"])


def _prefer_controle_index_item(
    candidate: ControleAssinaturasItem,
    current: ControleAssinaturasItem,
) -> bool:
    if is_controle_contratos_trigger_item(candidate) and not is_controle_contratos_trigger_item(
        current,
    ):
        return True
    return False


def update_controle_tipo(
    *,
    api_token: str,
    item_id: str,
    tipo_label: str,
) -> None:
    """Preenche coluna Tipo no item gatilho (sem alterar status)."""
    column_details = _load_controle_column_details(api_token=api_token)
    column_by_title = {detail.column.title.casefold(): detail.column for detail in column_details}
    tipo_col = columns_by_id_or_title(column_by_title, CONTROLE_COL_TIPO, ("tipo",))
    if not tipo_col:
        return
    column_values = _sanitize_column_values(
        column_details,
        {tipo_col.id: format_column_value(tipo_col.column_type, tipo_label)},
    )
    if not column_values:
        return
    _apply_controle_column_values(
        api_token=api_token,
        item_id=item_id,
        column_details=column_details,
        column_values=column_values,
    )


def update_controle_mirror_assinado(
    *,
    api_token: str,
    item_id: str,
    signed_at: date,
    group_id: str,
    current_group_id: str | None = None,
) -> None:
    """Marca fila espelho (Luciano) como Assinado sem Tipo e sem mover para grupo Assinados."""
    update_controle_item_progress(
        api_token=api_token,
        item_id=item_id,
        group_id=group_id,
        status_label=CONTROLE_STATUS_ASSINADO,
        signed_at=signed_at,
        current_group_id=current_group_id,
    )


def _extract_document_ids_from_text(text: str) -> set[str]:
    return extract_autentique_document_ids_from_text(text)


def _to_controle_item(
    item: dict,
    values: dict[str, str | None],
    signature_link: str,
    *,
    related_col_id: str | None = None,
    columns_by_id: dict[str, dict] | None = None,
) -> ControleAssinaturasItem:
    from classificacao_procons.contratos.parent_resolver import _parse_linked_item_ids

    related_ids: tuple[str, ...] = ()
    if related_col_id and columns_by_id and related_col_id in columns_by_id:
        raw_value = columns_by_id[related_col_id].get("value")
        if raw_value:
            related_ids = tuple(_parse_linked_item_ids(str(raw_value)))

    return ControleAssinaturasItem(
        item_id=str(item["id"]),
        name=str(item.get("name", "")),
        status=values.get(CONTROLE_COL_STATUS),
        tipo=values.get(CONTROLE_COL_TIPO),
        signature_link=signature_link or None,
        related_contract_item_ids=related_ids,
        group_id=str(item.get("group", {}).get("id")) if item.get("group", {}).get("id") else None,
    )


def ensure_autentique_id_on_controle_items(
    *,
    api_token: str,
    document_id: str,
    items: tuple[ControleAssinaturasItem, ...] | list[ControleAssinaturasItem],
) -> None:
    """Grava o ID do Autentique no link de assinatura de itens legados (um ID por item)."""
    normalized_id = document_id.casefold().strip()
    if not normalized_id:
        return

    column_details = _load_controle_column_details(api_token=api_token)
    column_by_title = {detail.column.title.casefold(): detail.column for detail in column_details}
    link_col = columns_by_id_or_title(
        column_by_title,
        CONTROLE_COL_LINK_ASSINATURA,
        ("link autentique", "assinatura", "link"),
    )
    if link_col is None:
        return

    for item in items:
        current = (item.signature_link or "").strip()
        existing_ids = autentique_ids_in_controle_link(current)
        if normalized_id in {token.casefold() for token in existing_ids}:
            continue
        if not existing_ids:
            if current:
                updated_text = f"{current}\nAutentique ID: {document_id}"
            else:
                updated_text = f"Autentique ID: {document_id}"
        else:
            updated_text = rebuild_controle_signature_link_text(
                previous_link=current or None,
                document_id=document_id,
            )
        column_values = _sanitize_column_values(
            column_details,
            {link_col.id: format_column_value(link_col.column_type, updated_text)},
        )
        if not column_values:
            continue
        _apply_controle_column_values(
            api_token=api_token,
            item_id=item.item_id,
            column_details=column_details,
            column_values=column_values,
        )


def update_controle_item_signature_link(
    *,
    api_token: str,
    item_id: str,
    signature_link_text: str,
) -> None:
    """Atualiza somente o campo de link de assinatura no Controle."""
    column_details = _load_controle_column_details(api_token=api_token)
    column_by_title = {detail.column.title.casefold(): detail.column for detail in column_details}
    link_col = columns_by_id_or_title(
        column_by_title,
        CONTROLE_COL_LINK_ASSINATURA,
        ("link autentique", "assinatura", "link"),
    )
    if link_col is None:
        return
    column_values = _sanitize_column_values(
        column_details,
        {link_col.id: format_column_value(link_col.column_type, signature_link_text)},
    )
    if not column_values:
        return
    _apply_controle_column_values(
        api_token=api_token,
        item_id=item_id,
        column_details=column_details,
        column_values=column_values,
    )


def archive_controle_item(*, api_token: str, item_id: str) -> None:
    """Arquiva item duplicado no quadro Controle Assinaturas (reversível no Monday)."""
    _graphql_request(
        api_token=api_token,
        query="""
        mutation ($itemId: ID!) {
          archive_item(item_id: $itemId) { id }
        }
        """,
        variables={"itemId": item_id},
    )


def update_controle_item_progress(
    *,
    api_token: str,
    item_id: str,
    group_id: str,
    status_label: str,
    signed_at: date | None = None,
    current_group_id: str | None = None,
) -> None:
    """Atualiza status/grupo de item pendente no Controle (sem alterar Tipo)."""
    column_values: dict[str, object] = {
        CONTROLE_COL_STATUS: {"label": status_label},
    }
    if signed_at is not None:
        column_values[CONTROLE_COL_DATA_ASSINATURA] = {"date": signed_at.isoformat()}

    _graphql_request(
        api_token=api_token,
        query="""
        mutation ($boardId: ID!, $itemId: ID!, $columnValues: JSON!) {
          change_multiple_column_values(
            board_id: $boardId
            item_id: $itemId
            column_values: $columnValues
          ) { id }
        }
        """,
        variables={
            "boardId": MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
            "itemId": item_id,
            "columnValues": json.dumps(column_values),
        },
    )

    if group_id and group_id != current_group_id:
        _graphql_request(
            api_token=api_token,
            query="""
            mutation ($itemId: ID!, $groupId: String!) {
              move_item_to_group(item_id: $itemId, group_id: $groupId) { id }
            }
            """,
            variables={"itemId": item_id, "groupId": group_id},
        )


def update_controle_item_fields(
    *,
    api_token: str,
    item_id: str,
    group_id: str | None = None,
    current_group_id: str | None = None,
    status_label: str | None = None,
    signed_at: date | None = None,
    tipo_label: str | None = None,
    signer_label: str | None = None,
    platform_name: str | None = None,
    inclusion_date: date | None = None,
    signature_link_text: str | None = None,
    clear_tipo: bool = False,
) -> None:
    """Atualiza colunas do Controle sem recriar o item."""
    column_details = _load_controle_column_details(api_token=api_token)
    column_by_title = {detail.column.title.casefold(): detail.column for detail in column_details}
    values: dict[str, Any] = {}

    if status_label is not None:
        status_col = columns_by_id_or_title(column_by_title, CONTROLE_COL_STATUS, ("status",))
        if status_col:
            values[status_col.id] = format_column_value(status_col.column_type, status_label)

    if signed_at is not None:
        data_col = columns_by_id_or_title(
            column_by_title,
            CONTROLE_COL_DATA_ASSINATURA,
            ("data",),
        )
        if data_col:
            values[data_col.id] = format_column_value(data_col.column_type, signed_at)

    if clear_tipo:
        tipo_col = columns_by_id_or_title(column_by_title, CONTROLE_COL_TIPO, ("tipo",))
        if tipo_col:
            values[tipo_col.id] = format_column_value(tipo_col.column_type, "")
    elif tipo_label is not None:
        tipo_col = columns_by_id_or_title(column_by_title, CONTROLE_COL_TIPO, ("tipo",))
        if tipo_col:
            values[tipo_col.id] = format_column_value(tipo_col.column_type, tipo_label)

    if signature_link_text is not None:
        link_col = columns_by_id_or_title(
            column_by_title,
            CONTROLE_COL_LINK_ASSINATURA,
            ("link autentique", "assinatura", "link"),
        )
        if link_col:
            values[link_col.id] = format_column_value(
                link_col.column_type,
                signature_link_text,
            )

    quem_col = _find_column(column_by_title, ("quem assina",))
    if quem_col and signer_label:
        values[quem_col.id] = format_column_value(quem_col.column_type, signer_label)

    platform_col = _find_column(
        column_by_title,
        ("nome da plataforma", "plataforma"),
    )
    if platform_col and platform_name:
        values[platform_col.id] = format_column_value(platform_col.column_type, platform_name)

    inclusion_col = _find_column(
        column_by_title,
        ("data de inclusao", "inclusão na plataforma", "inclusao"),
    )
    if inclusion_col and inclusion_date:
        values[inclusion_col.id] = format_column_value(inclusion_col.column_type, inclusion_date)

    column_values = _sanitize_column_values(column_details, values)
    if column_values:
        _apply_controle_column_values(
            api_token=api_token,
            item_id=item_id,
            column_details=column_details,
            column_values=column_values,
        )

    if group_id and group_id != current_group_id:
        _graphql_request(
            api_token=api_token,
            query="""
            mutation ($itemId: ID!, $groupId: String!) {
              move_item_to_group(item_id: $itemId, group_id: $groupId) { id }
            }
            """,
            variables={"itemId": item_id, "groupId": group_id},
        )


def update_controle_assinado(
    *,
    api_token: str,
    item_id: str,
    signed_pdf_url: str,
    signed_at: date,
) -> None:
    """Atualiza item do Controle Assinaturas para Assinado e move para grupo Assinados."""
    column_values = {
        CONTROLE_COL_STATUS: {"label": CONTROLE_STATUS_ASSINADO},
        CONTROLE_COL_DATA_ASSINATURA: {"date": signed_at.isoformat()},
        CONTROLE_COL_LINK_ASSINADO: format_link_column_value(
            url=signed_pdf_url,
            text="Contrato assinado",
        ),
    }
    _graphql_request(
        api_token=api_token,
        query="""
        mutation ($boardId: ID!, $itemId: ID!, $columnValues: JSON!) {
          change_multiple_column_values(
            board_id: $boardId
            item_id: $itemId
            column_values: $columnValues
          ) { id }
        }
        """,
        variables={
            "boardId": MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
            "itemId": item_id,
            "columnValues": json.dumps(column_values),
        },
    )
    _graphql_request(
        api_token=api_token,
        query="""
        mutation ($itemId: ID!, $groupId: String!) {
          move_item_to_group(item_id: $itemId, group_id: $groupId) { id }
        }
        """,
        variables={"itemId": item_id, "groupId": CONTROLE_GROUP_ASSINADOS},
    )


def register_contrato_item(
    *,
    api_token: str,
    metadata: ContractMetadata,
    document_name: str,
    signed_pdf_url: str,
    tipo_label: str | None,
    pdf_path: Path | None = None,
) -> MondayContractRegistrationResult:
    """Cria item no quadro Contratos com metadados extraídos."""
    board_context = load_board_metadata(
        api_token=api_token,
        board_id=MONDAY_CONTRATOS_BOARD_ID,
    )
    column_details = _load_contratos_column_details(api_token=api_token)
    columns = [detail.column for detail in column_details]
    resolved_tipo = tipo_label or infer_monday_tipo(
        document_name=document_name,
        category=infer_category(document_name=document_name, contract_type=metadata.contract_type),
    )
    group_id = _resolve_contratos_group_id(
        api_token=api_token,
        tipo_label=resolved_tipo,
    )
    item_name = metadata.counterparty_name or document_name
    column_values = _sanitize_column_values(
        column_details,
        _build_contratos_column_values(
            columns,
            metadata=metadata,
            signed_pdf_url=signed_pdf_url,
            document_name=document_name,
        ),
    )
    item_id = _create_contratos_item(
        api_token=api_token,
        group_id=group_id,
        item_name=item_name,
        column_values={},
    )
    _apply_contratos_column_values(
        api_token=api_token,
        item_id=item_id,
        column_details=column_details,
        column_values=column_values,
        pdf_path=pdf_path,
    )
    item_url = None
    if board_context.account_slug:
        item_url = (
            f"https://{board_context.account_slug}.monday.com/boards/"
            f"{MONDAY_CONTRATOS_BOARD_ID}/pulses/{item_id}"
        )
    return MondayContractRegistrationResult(
        controle_item_id=None,
        contratos_item_id=item_id,
        contratos_item_url=item_url,
        registration_mode="top_level",
    )


def find_parent_contrato_item(
    *,
    api_token: str,
    document_name: str,
    metadata: ContractMetadata,
    controle_item: ControleAssinaturasItem | None = None,
    min_score: int = 70,
) -> str | None:
    """Localiza item pai no quadro Contratos (wrapper legado)."""
    from classificacao_procons.contratos.parent_resolver import resolve_parent_contrato_item

    result = resolve_parent_contrato_item(
        api_token=api_token,
        document_name=document_name,
        metadata=metadata,
        controle_item=controle_item,
        min_name_score=min_score,
    )
    return result.parent_item_id


def register_contrato_subitem(
    *,
    api_token: str,
    parent_item_id: str,
    metadata: ContractMetadata,
    document_name: str,
    signed_pdf_url: str,
    pdf_path: Path | None = None,
) -> MondayContractRegistrationResult:
    """Cria subitem no quadro Contratos vinculado ao contrato pai."""
    board_context = load_board_metadata(
        api_token=api_token,
        board_id=MONDAY_CONTRATOS_BOARD_ID,
    )
    column_details = _load_contratos_column_details(api_token=api_token)
    columns = [detail.column for detail in column_details]
    item_name = document_name
    column_values = _sanitize_column_values(
        column_details,
        _build_contratos_column_values(
            columns,
            metadata=metadata,
            signed_pdf_url=signed_pdf_url,
            document_name=document_name,
        ),
    )
    item_id = _create_contratos_subitem(
        api_token=api_token,
        parent_item_id=parent_item_id,
        item_name=item_name,
    )
    _apply_contratos_column_values(
        api_token=api_token,
        item_id=item_id,
        column_details=column_details,
        column_values=column_values,
        pdf_path=pdf_path,
    )
    item_url = None
    if board_context.account_slug:
        item_url = (
            f"https://{board_context.account_slug}.monday.com/boards/"
            f"{MONDAY_CONTRATOS_BOARD_ID}/pulses/{item_id}"
        )
    return MondayContractRegistrationResult(
        controle_item_id=None,
        contratos_item_id=item_id,
        contratos_item_url=item_url,
        registration_mode="subitem",
        parent_item_id=parent_item_id,
    )


def _create_contratos_subitem(
    *,
    api_token: str,
    parent_item_id: str,
    item_name: str,
) -> str:
    data = _graphql_request(
        api_token=api_token,
        query="""
        mutation ($parentItemId: ID!, $itemName: String!) {
          create_subitem(parent_item_id: $parentItemId, item_name: $itemName) { id }
        }
        """,
        variables={
            "parentItemId": parent_item_id,
            "itemName": item_name,
        },
    )
    return str(data["create_subitem"]["id"])


def fetch_contratos_item_name(*, api_token: str, item_id: str) -> str:
    """Retorna nome do item no quadro Contratos."""
    data = _graphql_request(
        api_token=api_token,
        query="""
        query ($itemIds: [ID!]) {
          items(ids: $itemIds) {
            id
            name
          }
        }
        """,
        variables={"itemIds": [item_id]},
    )
    items = data.get("items", [])
    if not items:
        raise MondayClientError(f'Item "{item_id}" não encontrado no Monday.')
    return str(items[0].get("name", ""))


def enrich_contratos_item_columns(
    *,
    api_token: str,
    item_id: str,
    metadata: ContractMetadata,
    document_name: str,
    signed_pdf_url: str | None = None,
    pdf_path: Path | None = None,
) -> None:
    """Preenche colunas de item existente no quadro Contratos (webhook Monday)."""
    column_details = _load_contratos_column_details(api_token=api_token)
    columns = [detail.column for detail in column_details]
    column_values = _sanitize_column_values(
        column_details,
        _build_contratos_column_values(
            columns,
            metadata=metadata,
            signed_pdf_url=signed_pdf_url or "",
            document_name=document_name,
        ),
    )
    _apply_contratos_column_values(
        api_token=api_token,
        item_id=item_id,
        column_details=column_details,
        column_values=column_values,
        pdf_path=pdf_path,
    )


def _normalize_group_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


def _resolve_contratos_group_id(*, api_token: str, tipo_label: str) -> str:
    mapped = CONTRATOS_GROUP_BY_TIPO.get(tipo_label)
    if mapped and tipo_label not in DYNAMIC_CONTRATOS_GROUP_TITLES:
        return mapped
    if tipo_label in DYNAMIC_CONTRATOS_GROUP_TITLES:
        return _ensure_board_group(api_token=api_token, group_title=tipo_label)
    return mapped or DEFAULT_CONTRATOS_GROUP_ID


def _ensure_board_group(*, api_token: str, group_title: str) -> str:
    data = _graphql_request(
        api_token=api_token,
        query="""
        query ($boardId: [ID!]) {
          boards(ids: $boardId) {
            groups { id title }
          }
        }
        """,
        variables={"boardId": MONDAY_CONTRATOS_BOARD_ID},
    )
    boards = data.get("boards", [])
    if boards:
        target = _normalize_group_title(group_title)
        for group in boards[0].get("groups", []):
            if _normalize_group_title(str(group.get("title", ""))) == target:
                return str(group["id"])

    created = _graphql_request(
        api_token=api_token,
        query="""
        mutation ($boardId: ID!, $groupName: String!) {
          create_group(board_id: $boardId, group_name: $groupName) { id }
        }
        """,
        variables={"boardId": MONDAY_CONTRATOS_BOARD_ID, "groupName": group_title},
    )
    return str(created["create_group"]["id"])


def _apply_contratos_column_values(
    *,
    api_token: str,
    item_id: str,
    column_details: list[MondayColumnDetails],
    column_values: dict[str, Any],
    pdf_path: Path | None,
) -> None:
    details_by_id = {detail.column.id: detail for detail in column_details}
    contrato_column = _find_contrato_column([detail.column for detail in column_details])

    for column_id, value in column_values.items():
        detail = details_by_id.get(column_id)
        if detail is None:
            continue

        column_type = detail.column.column_type
        if column_type == "file":
            if pdf_path is None or contrato_column is None or contrato_column.id != column_id:
                continue
            try:
                upload_file_to_column(
                    api_token=api_token,
                    item_id=item_id,
                    column_id=column_id,
                    file_path=pdf_path,
                )
            except MondayClientError:
                continue
            continue

        try:
            _graphql_request(
                api_token=api_token,
                query="""
                mutation ($boardId: ID!, $itemId: ID!, $columnValues: JSON!) {
                  change_multiple_column_values(
                    board_id: $boardId
                    item_id: $itemId
                    column_values: $columnValues
                  ) { id }
                }
                """,
                variables={
                    "boardId": MONDAY_CONTRATOS_BOARD_ID,
                    "itemId": item_id,
                    "columnValues": json.dumps({column_id: value}),
                },
            )
        except MondayClientError:
            continue

    if (
        pdf_path is not None
        and contrato_column is not None
        and contrato_column.column_type == "file"
        and contrato_column.id not in column_values
    ):
        try:
            upload_file_to_column(
                api_token=api_token,
                item_id=item_id,
                column_id=contrato_column.id,
                file_path=pdf_path,
            )
        except MondayClientError:
            return


def _find_contrato_column(columns: list[MondayColumn]) -> MondayColumn | None:
    column_by_title = {column.title.casefold(): column for column in columns}
    return _find_column(column_by_title, ("contrato",), exact=True)


def _load_contratos_column_details(*, api_token: str) -> list[MondayColumnDetails]:
    data = _graphql_request(
        api_token=api_token,
        query="""
        query ($boardId: [ID!]) {
          boards(ids: $boardId) {
            columns {
              id
              title
              type
              settings_str
            }
          }
        }
        """,
        variables={"boardId": MONDAY_CONTRATOS_BOARD_ID},
    )
    boards = data.get("boards", [])
    if not boards:
        return []
    return [
        MondayColumnDetails(
            column=MondayColumn(
                id=str(column["id"]),
                title=str(column.get("title", "")),
                column_type=str(column.get("type", "")),
            ),
            settings_str=column.get("settings_str"),
        )
        for column in boards[0].get("columns", [])
    ]


def _allowed_labels(settings_str: str | None, column_type: str) -> set[str] | None:
    if not settings_str:
        return None
    try:
        settings = json.loads(settings_str)
    except json.JSONDecodeError:
        return None

    if column_type in {"status", "color"}:
        labels = settings.get("labels", {})
        if isinstance(labels, dict):
            return {str(label).casefold() for label in labels.values() if str(label).strip()}
        return None

    if column_type == "dropdown":
        labels = settings.get("labels", [])
        if isinstance(labels, list):
            names: list[str] = []
            for item in labels:
                if isinstance(item, dict):
                    names.append(str(item.get("name", "")))
                else:
                    names.append(str(item))
            return {name.casefold() for name in names if name.strip()}
        return None

    return None


def _sanitize_column_values(
    column_details: list[MondayColumnDetails],
    values: dict[str, Any],
) -> dict[str, Any]:
    details_by_id = {detail.column.id: detail for detail in column_details}
    sanitized: dict[str, Any] = {}

    for column_id, value in values.items():
        detail = details_by_id.get(column_id)
        if detail is None:
            continue

        column_type = detail.column.column_type
        if column_type in {"status", "color"} and isinstance(value, dict) and "label" in value:
            allowed = _allowed_labels(detail.settings_str, column_type)
            label = str(value["label"])
            if allowed is not None and label.casefold() not in allowed:
                continue

        if column_type == "dropdown" and isinstance(value, dict) and "labels" in value:
            allowed = _allowed_labels(detail.settings_str, column_type)
            labels = [str(item) for item in value.get("labels", [])]
            if allowed is not None:
                labels = [label for label in labels if label.casefold() in allowed]
                if not labels:
                    continue
            value = {"labels": labels}

        sanitized[column_id] = value

    return sanitized


def _create_contratos_item(
    *,
    api_token: str,
    group_id: str,
    item_name: str,
    column_values: dict[str, Any],
) -> str:
    data = _graphql_request(
        api_token=api_token,
        query="""
        mutation ($boardId: ID!, $groupId: String!, $itemName: String!, $columnValues: JSON) {
          create_item(
            board_id: $boardId
            group_id: $groupId
            item_name: $itemName
            column_values: $columnValues
          ) { id }
        }
        """,
        variables={
            "boardId": MONDAY_CONTRATOS_BOARD_ID,
            "groupId": group_id,
            "itemName": item_name,
            "columnValues": json.dumps(column_values) if column_values else None,
        },
    )
    return str(data["create_item"]["id"])


def _build_contratos_column_values(
    columns: list[MondayColumn],
    *,
    metadata: ContractMetadata,
    signed_pdf_url: str,
    document_name: str,
) -> dict[str, Any]:
    column_by_title = {column.title.casefold(): column for column in columns}
    values: dict[str, Any] = {}

    empresa_col = _find_column(column_by_title, ("empresa",))
    if empresa_col and metadata.company:
        values[empresa_col.id] = format_column_value(empresa_col.column_type, metadata.company)

    cnpj_col = _find_column(column_by_title, ("cnpj",))
    if cnpj_col and metadata.counterparty_cnpj:
        values[cnpj_col.id] = format_column_value(
            cnpj_col.column_type,
            metadata.counterparty_cnpj,
        )

    tipo_col = _find_column(column_by_title, ("tipo de contrato",))
    if tipo_col and metadata.contract_type:
        values[tipo_col.id] = format_column_value(tipo_col.column_type, metadata.contract_type)

    data_col = _find_column(column_by_title, ("data do contrato",))
    if data_col and metadata.start_date:
        values[data_col.id] = format_column_value(data_col.column_type, metadata.start_date)

    termino_col = _find_column(column_by_title, ("término", "termino"))
    if termino_col and metadata.end_date:
        values[termino_col.id] = format_column_value(termino_col.column_type, metadata.end_date)

    contrato_col = _find_column(column_by_title, ("contrato",), exact=True)
    if contrato_col:
        if contrato_col.column_type == "file":
            values[contrato_col.id] = None
        else:
            values[contrato_col.id] = format_column_value(
                contrato_col.column_type,
                signed_pdf_url,
                link_text=document_name,
            )

    vigencia_col = _find_column(column_by_title, ("vigência", "vigencia"))
    if vigencia_col:
        label = "Vigente"
        if metadata.end_date and metadata.end_date < date.today():
            label = "Não Vigente"
        values[vigencia_col.id] = format_column_value(vigencia_col.column_type, label)

    obs_col = _find_column(column_by_title, ("observações", "observacoes"))
    if obs_col and metadata.summary:
        values[obs_col.id] = format_column_value(obs_col.column_type, metadata.summary)

    return {key: value for key, value in values.items() if value is not None}


def _find_column(
    column_by_title: dict[str, MondayColumn],
    keywords: tuple[str, ...],
    *,
    exact: bool = False,
) -> MondayColumn | None:
    for title, column in column_by_title.items():
        if exact:
            if title in keywords:
                return column
            continue
        if any(keyword in title for keyword in keywords):
            return column
    return None
