"""Integração Monday.com para contratos assinados."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
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
    MONDAY_CONTRATOS_BOARD_ID,
    MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
)
from classificacao_procons.contratos.drive_routing import infer_category, infer_monday_tipo
from classificacao_procons.contratos.gemini_extractor import ContractMetadata
from classificacao_procons.monday.client import _graphql_request, load_board_metadata
from classificacao_procons.monday.mapping import MondayColumn, format_link_column_value


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
) -> MondayContractRegistrationResult:
    """Cria item no quadro Contratos com metadados extraídos."""
    board_context = load_board_metadata(
        api_token=api_token,
        board_id=MONDAY_CONTRATOS_BOARD_ID,
    )
    resolved_tipo = tipo_label or infer_monday_tipo(
        document_name=document_name,
        category=infer_category(document_name=document_name, contract_type=metadata.contract_type),
    )
    group_id = CONTRATOS_GROUP_BY_TIPO.get(resolved_tipo, DEFAULT_CONTRATOS_GROUP_ID)
    item_name = metadata.counterparty_name or document_name
    column_values = _build_contratos_column_values(
        board_context.columns,
        metadata=metadata,
        signed_pdf_url=signed_pdf_url,
        document_name=document_name,
    )

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
    item_id = str(data["create_item"]["id"])
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
        values[empresa_col.id] = {"label": metadata.company}

    cnpj_col = _find_column(column_by_title, ("cnpj",))
    if cnpj_col and metadata.counterparty_cnpj:
        values[cnpj_col.id] = metadata.counterparty_cnpj

    tipo_col = _find_column(column_by_title, ("tipo de contrato",))
    if tipo_col and metadata.contract_type:
        values[tipo_col.id] = metadata.contract_type

    data_col = _find_column(column_by_title, ("data do contrato",))
    if data_col and metadata.start_date:
        values[data_col.id] = {"date": metadata.start_date.isoformat()}

    termino_col = _find_column(column_by_title, ("término", "termino"))
    if termino_col and metadata.end_date:
        values[termino_col.id] = {"date": metadata.end_date.isoformat()}

    contrato_col = _find_column(column_by_title, ("contrato",))
    if contrato_col:
        values[contrato_col.id] = format_link_column_value(
            url=signed_pdf_url,
            text=document_name,
        )

    vigencia_col = _find_column(column_by_title, ("vigência", "vigencia"))
    if vigencia_col:
        label = "Vigente"
        if metadata.end_date and metadata.end_date < date.today():
            label = "Não Vigente"
        values[vigencia_col.id] = {"label": label}

    obs_col = _find_column(column_by_title, ("observações", "observacoes"))
    if obs_col and metadata.summary:
        values[obs_col.id] = metadata.summary

    return values


def _find_column(
    column_by_title: dict[str, MondayColumn],
    keywords: tuple[str, ...],
) -> MondayColumn | None:
    for title, column in column_by_title.items():
        if any(keyword in title for keyword in keywords):
            return column
    return None
