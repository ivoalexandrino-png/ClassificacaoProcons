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
from classificacao_procons.monday.client import (
    MondayClientError,
    _graphql_request,
    load_board_metadata,
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
    column_details = _load_contratos_column_details(api_token=api_token)
    columns = [detail.column for detail in column_details]
    resolved_tipo = tipo_label or infer_monday_tipo(
        document_name=document_name,
        category=infer_category(document_name=document_name, contract_type=metadata.contract_type),
    )
    group_id = CONTRATOS_GROUP_BY_TIPO.get(resolved_tipo, DEFAULT_CONTRATOS_GROUP_ID)
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
    item_id = _create_contratos_item_with_fallback(
        api_token=api_token,
        column_details=column_details,
        group_id=group_id,
        item_name=item_name,
        column_values=column_values,
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


def _is_retryable_monday_error(exc: MondayClientError) -> bool:
    message = str(exc).casefold()
    return "invalid value" in message or "internal server error" in message


def _create_contratos_item_with_fallback(
    *,
    api_token: str,
    column_details: list[MondayColumnDetails],
    group_id: str,
    item_name: str,
    column_values: dict[str, Any],
) -> str:
    link_column_ids = {
        detail.column.id
        for detail in column_details
        if detail.column.column_type == "link" and detail.column.title.casefold() == "contrato"
    }
    link_only_values = {
        column_id: value
        for column_id, value in column_values.items()
        if column_id in link_column_ids
    }

    attempts: list[dict[str, Any]] = []
    if column_values:
        attempts.append(column_values)
    if link_only_values and link_only_values != column_values:
        attempts.append(link_only_values)
    attempts.append({})

    last_error: MondayClientError | None = None
    for attempt_values in attempts:
        try:
            return _create_contratos_item(
                api_token=api_token,
                group_id=group_id,
                item_name=item_name,
                column_values=attempt_values,
            )
        except MondayClientError as exc:
            last_error = exc
            if not _is_retryable_monday_error(exc):
                raise

    if last_error is not None:
        raise last_error
    raise MondayClientError("Não foi possível criar item no quadro Contratos.")


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

    return values


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
