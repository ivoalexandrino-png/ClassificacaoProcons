"""Cliente REST do Sunday (sunday.b4a.ai).

O Sunday expõe uma API REST (NestJS em Cloud Run), autenticada por Personal
Access Token via ``Authorization: Bearer <token>``. Endpoint e token vêm das
variáveis ``SUNDAY_API_URL``/``SUNDAY_API_TOKEN`` (ou os overrides genéricos
``LEGAL_API_URL``/``LEGAL_API_TOKEN``).

Este módulo cobre o **caminho de leitura** (workspaces, boards, colunas, grupos,
itens), suficiente para o canário de leitura da migração. Escrita será adicionada
quando os endpoints POST/PATCH forem confirmados (ver doc de migração).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from classificacao_procons.sunday.models import (
    SundayBoard,
    SundayColumn,
    SundayGroup,
    SundayItem,
    SundayWorkspace,
)
from classificacao_procons.sunday.parser import (
    parse_board,
    parse_boards,
    parse_columns,
    parse_groups,
    parse_items,
    parse_workspace,
    parse_workspaces,
)

ENV_SUNDAY_API_URL = "SUNDAY_API_URL"
ENV_SUNDAY_API_TOKEN = "SUNDAY_API_TOKEN"
ENV_GENERIC_API_URL = "LEGAL_API_URL"
ENV_GENERIC_API_TOKEN = "LEGAL_API_TOKEN"

_REQUEST_TIMEOUT_SECONDS = 30
_MAX_RETRIES = 3
_RETRY_BASE_DELAY_SECONDS = 2


class SundayClientError(RuntimeError):
    """Erro ao falar com a API do Sunday."""


def _env(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


def get_api_url_from_env() -> str | None:
    return _env(ENV_SUNDAY_API_URL) or _env(ENV_GENERIC_API_URL)


def get_api_token_from_env() -> str | None:
    return _env(ENV_SUNDAY_API_TOKEN) or _env(ENV_GENERIC_API_TOKEN)


@dataclass(frozen=True)
class SundayClient:
    """Cliente REST fino do Sunday (leitura)."""

    api_url: str
    api_token: str

    @classmethod
    def from_env(cls) -> SundayClient:
        api_url = get_api_url_from_env()
        if not api_url:
            raise SundayClientError(
                f"{ENV_SUNDAY_API_URL} não configurada (endpoint da API do Sunday).",
            )
        token = get_api_token_from_env()
        if not token:
            raise SundayClientError(f"{ENV_SUNDAY_API_TOKEN} não configurada.")
        return cls(api_url=api_url.rstrip("/"), api_token=token)

    def _request(self, method: str, path: str) -> object:
        url = f"{self.api_url}{path}"
        last_error: SundayClientError | None = None

        for attempt in range(_MAX_RETRIES):
            request = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Accept": "application/json",
                },
                method=method,
            )
            try:
                with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
                    body = response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                last_error = SundayClientError(f"Sunday API HTTP {exc.code}: {error_body}")
                if exc.code in {500, 502, 503, 504} and attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_BASE_DELAY_SECONDS * (2**attempt))
                    continue
                raise last_error from exc
            except urllib.error.URLError as exc:
                last_error = SundayClientError(f"Sunday API indisponível: {exc.reason}")
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_BASE_DELAY_SECONDS * (2**attempt))
                    continue
                raise last_error from exc
            except OSError as exc:
                last_error = SundayClientError(f"Sunday API indisponível: {exc}")
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_BASE_DELAY_SECONDS * (2**attempt))
                    continue
                raise last_error from exc

            try:
                return json.loads(body)
            except json.JSONDecodeError as exc:
                raise SundayClientError("Sunday API retornou resposta não-JSON.") from exc

        if last_error is not None:
            raise last_error
        raise SundayClientError("Sunday API não respondeu.")

    def _get_list(self, path: str) -> list:
        data = self._request("GET", path)
        if not isinstance(data, list):
            raise SundayClientError(f"Esperava lista em {path}, veio {type(data).__name__}.")
        return data

    def _get_dict(self, path: str) -> dict:
        data = self._request("GET", path)
        if not isinstance(data, dict):
            raise SundayClientError(f"Esperava objeto em {path}, veio {type(data).__name__}.")
        return data

    def get_me(self) -> dict:
        return self._get_dict("/auth/me")

    def list_workspaces(self) -> list[SundayWorkspace]:
        return parse_workspaces(self._get_list("/workspaces"))

    def get_workspace(self, workspace_id: str) -> SundayWorkspace:
        return parse_workspace(self._get_dict(f"/workspaces/{workspace_id}"))

    def list_boards(self, *, workspace_id: str | None = None) -> list[SundayBoard]:
        path = f"/boards?workspace_id={workspace_id}" if workspace_id else "/boards"
        return parse_boards(self._get_list(path))

    def get_board(self, board_id: str) -> SundayBoard:
        return parse_board(self._get_dict(f"/boards/{board_id}"))

    def list_columns(self, board_id: str) -> list[SundayColumn]:
        return parse_columns(self._get_list(f"/boards/{board_id}/columns"))

    def list_groups(self, board_id: str) -> list[SundayGroup]:
        return parse_groups(self._get_list(f"/boards/{board_id}/groups"))

    def list_items(self, board_id: str) -> list[SundayItem]:
        return parse_items(self._get_list(f"/boards/{board_id}/items"))
