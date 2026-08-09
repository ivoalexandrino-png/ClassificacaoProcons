"""Leitura das credenciais do Questor no board Acessos do Monday.

Reaproveita o mesmo board de acessos usado pelos portais Procon
(``credentials/monday_board.py``): item "Questor - Certidões", com colunas
Login/Senha. O link fica na URL do portal (passada por opção/ambiente), pois a
coluna de link do item pode estar vazia.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from classificacao_procons.credentials.mapping import normalize_label, resolve_field_for_column
from classificacao_procons.credentials.monday_board import get_credentials_board_id_from_env
from classificacao_procons.monday.client import (
    MondayClientError,
    _graphql_request,
    get_api_token_from_env,
)

# Elemento designado no board Acessos. Há dois itens "Questor - Certidões" no
# quadro; o item com sufixo "- Ivo" é o de credencial ativa (o outro retorna
# "Usuário não encontrado"). Sobrescreva com a env QUESTOR_MONDAY_ITEM.
ENV_ITEM_NAME = "QUESTOR_MONDAY_ITEM"
DEFAULT_ITEM_NAME = "Questor - Certidões - Ivo"

_BOARD_QUERY = """
query ($boardId: [ID!], $limit: Int!) {
  boards(ids: $boardId) {
    columns { id title type }
    groups {
      items_page(limit: $limit) {
        items { id name column_values { id text value } }
      }
    }
  }
}
"""


class QuestorCredentialsError(RuntimeError):
    """Credenciais do Questor não encontradas no Monday."""


@dataclass(frozen=True)
class QuestorCredentials:
    login: str
    password: str
    portal_url: str | None
    monday_item_id: str
    elemento: str


def _item_matches(name: str, query: str) -> bool:
    """Casa por igualdade normalizada ou por substring do nome designado."""
    folded_name = normalize_label(name)
    folded_query = normalize_label(query)
    return folded_name == folded_query or folded_query in folded_name


def get_item_name_from_env(item_name: str | None = None) -> str:
    if item_name:
        return item_name
    return os.environ.get(ENV_ITEM_NAME, DEFAULT_ITEM_NAME).strip() or DEFAULT_ITEM_NAME


def resolve_questor_credentials(
    *,
    api_token: str | None = None,
    board_id: str | None = None,
    item_name: str | None = None,
    limit: int = 200,
) -> QuestorCredentials:
    """Busca login/senha do Questor no board Acessos do Monday."""
    token = api_token or get_api_token_from_env()
    if not token:
        raise QuestorCredentialsError(
            "MONDAY_API_TOKEN não configurada para buscar credenciais do Questor.",
        )
    resolved_board_id = board_id or get_credentials_board_id_from_env()
    target_item = get_item_name_from_env(item_name)

    try:
        data = _graphql_request(
            api_token=token,
            query=_BOARD_QUERY,
            variables={"boardId": resolved_board_id, "limit": limit},
        )
    except MondayClientError as exc:
        raise QuestorCredentialsError(str(exc)) from exc

    boards = data.get("boards", [])
    if not boards:
        raise QuestorCredentialsError(f'Board "{resolved_board_id}" não encontrado.')
    board = boards[0]
    column_field = {
        column["id"]: resolve_field_for_column(column["title"])
        for column in board.get("columns", [])
    }

    for group in board.get("groups", []):
        for item in group.get("items_page", {}).get("items", []):
            if not _item_matches(item.get("name", ""), target_item):
                continue
            fields: dict[str, str] = {}
            for column_value in item.get("column_values", []):
                field = column_field.get(column_value.get("id", ""))
                if field:
                    fields[field] = (column_value.get("text") or "").strip()
            login = fields.get("login")
            password = fields.get("password")
            if not login or not password:
                raise QuestorCredentialsError(
                    f'Item "{item.get("name")}" sem Login/Senha preenchidos no Monday.',
                )
            return QuestorCredentials(
                login=login,
                password=password,
                portal_url=fields.get("link") or None,
                monday_item_id=str(item["id"]),
                elemento=str(item.get("name", "")).strip(),
            )

    raise QuestorCredentialsError(
        f'Item de credenciais do Questor "{target_item}" não encontrado no board.',
    )
