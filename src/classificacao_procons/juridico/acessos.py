"""Credenciais de portais de tribunais a partir do quadro "Acessos" do Monday.

O quadro (grupo "TJ's") guarda login/senha por tribunal e sistema (E-SAJ,
PROJUDI, EPROC…). As senhas nunca são logadas; só transitam em memória para
o login no portal.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from classificacao_procons.juridico.monday import (
    _graphql_request,
    _list_all_boards,
    _normalize_title,
    _pick_juridico_board,
)
from classificacao_procons.monday.client import get_api_token_from_env

ENV_ACESSOS_BOARD_ID = "MONDAY_ACESSOS_BOARD_ID"
DEFAULT_ACESSOS_BOARD_NAME = "acessos"


class AcessosError(RuntimeError):
    """Erro ao resolver credenciais no quadro Acessos."""


@dataclass(frozen=True)
class PortalCredential:
    tribunal: str
    system: str
    login: str
    password: str

    def __repr__(self) -> str:  # nunca expor a senha em logs/trace
        return (
            f"PortalCredential(tribunal={self.tribunal!r}, system={self.system!r}, "
            f"login={self.login!r}, password='***')"
        )


def _normalize_tribunal_name(value: str) -> str:
    """"TJ- SP", "TJ-SP" e "TJSP" viram "tjsp"."""
    return re.sub(r"[\s\-–_]+", "", _normalize_title(value))


def _board_id(api_token: str) -> str:
    board_id = os.environ.get(ENV_ACESSOS_BOARD_ID, "").strip()
    if board_id:
        return board_id
    boards = [
        board
        for board in _list_all_boards(api_token)
        if _normalize_title(str(board.get("name", ""))) == DEFAULT_ACESSOS_BOARD_NAME
    ]
    board = boards[0] if boards else _pick_juridico_board(
        _list_all_boards(api_token),
        DEFAULT_ACESSOS_BOARD_NAME,
    )
    if not board:
        raise AcessosError('Quadro "Acessos" não encontrado no Monday.')
    return str(board["id"])


def list_portal_credentials(api_token: str | None = None) -> list[PortalCredential]:
    """Lista as credenciais de tribunais (grupo TJ's/STF) do quadro Acessos."""
    token = api_token or get_api_token_from_env()
    if not token:
        raise AcessosError("MONDAY_API_TOKEN não configurada.")

    data = _graphql_request(
        api_token=token,
        query="""
        query ($boardId: ID!) {
          boards(ids: [$boardId]) {
            items_page (limit: 200) {
              items {
                name
                group { title }
                column_values { column { title } text }
              }
            }
          }
        }
        """,
        variables={"boardId": _board_id(token)},
    )
    boards = data.get("boards", [])
    items = boards[0].get("items_page", {}).get("items", []) if boards else []

    credentials: list[PortalCredential] = []
    for item in items:
        values = {
            _normalize_title(str(cv.get("column", {}).get("title", ""))): str(cv.get("text") or "")
            for cv in item.get("column_values", [])
        }
        login = values.get("login", "").strip()
        password = values.get("senha", "").strip()
        if not login or not password:
            continue
        credentials.append(
            PortalCredential(
                tribunal=str(item.get("name", "")).strip(),
                system=values.get("sistema", "").strip().upper(),
                login=login,
                password=password,
            ),
        )
    return credentials


def get_tribunal_credential(
    tribunal_acronym: str,
    *,
    api_token: str | None = None,
) -> PortalCredential | None:
    """Credencial do tribunal (ex.: "TJSP" casa com o item "TJ-SP")."""
    target = _normalize_tribunal_name(tribunal_acronym)
    for credential in list_portal_credentials(api_token=api_token):
        if _normalize_tribunal_name(credential.tribunal) == target:
            return credential
    return None
