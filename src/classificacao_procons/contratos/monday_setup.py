"""Setup de colunas Monday para o fluxo de contratos."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from classificacao_procons.contratos.constants import (
    MONDAY_CONTRATOS_BOARD_ID,
    MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
)
from classificacao_procons.monday.client import MONDAY_API_URL, MondayClientError

CONTROLE_COL_CONTRATO_RELACIONADO_TITLE = "Contrato relacionado"
MONDAY_SETUP_API_VERSION = "2025-10"


@dataclass(frozen=True)
class RelatedContractColumnResult:
    column_id: str
    created: bool
    board_id: str


def _graphql_request_with_version(
    *,
    api_token: str,
    query: str,
    variables: dict | None = None,
    api_version: str,
) -> dict:
    payload: dict[str, object] = {"query": query}
    if variables:
        payload["variables"] = variables

    request = urllib.request.Request(
        MONDAY_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": api_token,
            "Content-Type": "application/json",
            "API-Version": api_version,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise MondayClientError(f"Monday API HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise MondayClientError(f"Monday API indisponível: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise MondayClientError("Monday API retornou resposta inválida.") from exc

    if body.get("errors"):
        messages = "; ".join(str(item.get("message", item)) for item in body["errors"])
        raise MondayClientError(messages)

    data = body.get("data")
    if data is None:
        raise MondayClientError("Monday API retornou payload vazio.")
    return data


def _load_controle_columns(*, api_token: str) -> list[dict[str, str]]:
    data = _graphql_request_with_version(
        api_token=api_token,
        api_version=MONDAY_SETUP_API_VERSION,
        query="""
        query ($boardId: [ID!]) {
          boards(ids: $boardId) {
            columns { id title type }
          }
        }
        """,
        variables={"boardId": MONDAY_CONTROLE_ASSINATURAS_BOARD_ID},
    )
    boards = data.get("boards", [])
    if not boards:
        return []
    return [
        {
            "id": str(column["id"]),
            "title": str(column.get("title", "")),
            "type": str(column.get("type", "")),
        }
        for column in boards[0].get("columns", [])
    ]


def _find_existing_related_contract_column(columns: list[dict[str, str]]) -> str | None:
    target_title = CONTROLE_COL_CONTRATO_RELACIONADO_TITLE.casefold()
    for column in columns:
        if column["title"].casefold() == target_title:
            return column["id"]
    for column in columns:
        if column["type"] in {"board_relation", "connect_boards"} and target_title in column[
            "title"
        ].casefold():
            return column["id"]
    return None


def ensure_controle_contrato_relacionado_column(*, api_token: str) -> RelatedContractColumnResult:
    """Garante coluna Connect boards 'Contrato relacionado' no Controle Assinaturas."""
    columns = _load_controle_columns(api_token=api_token)
    existing_id = _find_existing_related_contract_column(columns)
    if existing_id:
        return RelatedContractColumnResult(
            column_id=existing_id,
            created=False,
            board_id=MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
        )

    data = _graphql_request_with_version(
        api_token=api_token,
        api_version=MONDAY_SETUP_API_VERSION,
        query="""
        mutation ($boardId: ID!, $title: String!, $defaults: JSON!) {
          create_column(
            board_id: $boardId
            title: $title
            column_type: board_relation
            defaults: $defaults
          ) {
            id
            title
            type
          }
        }
        """,
        variables={
            "boardId": MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
            "title": CONTROLE_COL_CONTRATO_RELACIONADO_TITLE,
            "defaults": {
                "boardIds": [int(MONDAY_CONTRATOS_BOARD_ID)],
                "allowMultipleItems": False,
                "allowCreateReflectionColumn": False,
            },
        },
    )
    column = data.get("create_column")
    if not column or not column.get("id"):
        raise MondayClientError("Monday não retornou ID da coluna criada.")

    return RelatedContractColumnResult(
        column_id=str(column["id"]),
        created=True,
        board_id=MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
    )
