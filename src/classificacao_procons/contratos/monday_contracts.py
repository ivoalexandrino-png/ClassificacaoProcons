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
    CONTROLE_STATUS_ASSINADO,
    DEFAULT_CONTRATOS_GROUP_ID,
    DYNAMIC_CONTRATOS_GROUP_TITLES,
    MONDAY_CONTRATOS_BOARD_ID,
    MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
)
from classificacao_procons.contratos.drive_routing import infer_category, infer_monday_tipo
from classificacao_procons.contratos.gemini_extractor import ContractMetadata
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
class ControleAssinaturasItem:
    item_id: str
    name: str
    status: str | None
    tipo: str | None
    signature_link: str | None


@dataclass(frozen=True)
class MondayContractRegistrationResult:
    controle_item_id: str | None
    contratos_item_id: str | None
    contratos_item_url: str | None
    skipped_duplicate: bool = False


def find_controle_item(
    *,
    api_token: str,
    document_id: str,
    document_name: str,
) -> ControleAssinaturasItem | None:
    """Localiza item no Controle Assinaturas por ID/nome/link Autentique."""
    cursor: str | None = None
    normalized_name = document_name.casefold().strip()
    normalized_id = document_id.casefold().strip()

    for _ in range(30):
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
            values = {column["id"]: column.get("text") for column in item["column_values"]}
            signature_link = values.get(CONTROLE_COL_LINK_ASSINATURA) or ""
            item_name = str(item.get("name", ""))
            if normalized_id and normalized_id in signature_link.casefold():
                return _to_controle_item(item, values, signature_link)
            if normalized_name and normalized_name == item_name.casefold().strip():
                return _to_controle_item(item, values, signature_link)
            if normalized_name and normalized_name in item_name.casefold():
                return _to_controle_item(item, values, signature_link)

        cursor = page.get("cursor")
        if not cursor:
            break

    return None


@dataclass(frozen=True)
class ControleAssinaturasIndex:
    document_ids: frozenset[str]
    exact_names: frozenset[str]

    def matches_document(self, document: object) -> bool:
        document_id = str(getattr(document, "document_id", "")).casefold().strip()
        document_name = str(getattr(document, "name", "")).casefold().strip()
        if document_id and document_id in self.document_ids:
            return True
        if document_name and document_name in self.exact_names:
            return True
        signature_link = str(getattr(document, "primary_signature_link", lambda: None)() or "")
        if document_id and document_id in signature_link.casefold():
            return True
        for known_name in self.exact_names:
            if document_name and (document_name in known_name or known_name in document_name):
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
                    name
                    column_values(ids: ["long_text_mkvnwp6d"]) {
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
            for column in item.get("column_values", []):
                text = str(column.get("text") or "")
                value = str(column.get("value") or "")
                for token in _extract_document_ids_from_text(f"{text}\n{value}"):
                    document_ids.add(token)

        cursor = page.get("cursor")
        if not cursor:
            break

    return ControleAssinaturasIndex(
        document_ids=frozenset(document_ids),
        exact_names=frozenset(exact_names),
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


def _extract_document_ids_from_text(text: str) -> set[str]:
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


def _to_controle_item(
    item: dict,
    values: dict[str, str | None],
    signature_link: str,
) -> ControleAssinaturasItem:
    return ControleAssinaturasItem(
        item_id=str(item["id"]),
        name=str(item.get("name", "")),
        status=values.get(CONTROLE_COL_STATUS),
        tipo=values.get(CONTROLE_COL_TIPO),
        signature_link=signature_link or None,
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
