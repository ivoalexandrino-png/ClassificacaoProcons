"""Camada HTTP do cliente Sunday.

Centraliza base URL, autenticação (`X-Sunday-Token`), timeout, JSON, ETag/304 e o
mapeamento de erros. O transporte é injetável para testes (nenhum teste unitário
chama a API real).

Segurança do token: o valor nunca aparece em logs, exceções, `repr` ou relatórios —
ele existe apenas no header montado imediatamente antes do envio.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from classificacao_procons.sunday.errors import (
    SundayConfigError,
    SundayHTTPError,
    error_for_status,
)

DEFAULT_TIMEOUT_SECONDS = 30
ENV_API_URL = "SUNDAY_API_URL"
ENV_API_TOKEN = "SUNDAY_API_TOKEN"
TOKEN_HEADER = "X-Sunday-Token"
GET_RETRY_STATUSES = frozenset({500, 502, 503, 504})
GET_MAX_ATTEMPTS = 3
GET_RETRY_BASE_DELAY_SECONDS = 1.0

# Transporte: (method, url, body, headers, timeout) -> (status, corpo_texto, headers_resposta)
Transport = Callable[[str, str, bytes | None, dict[str, str], int], tuple[int, str, dict[str, str]]]


@dataclass(frozen=True)
class SundayConfig:
    """Configuração do cliente. O token fica fora do repr."""

    base_url: str
    token: str = field(repr=False)
    timeout: int = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> SundayConfig:
        base_url = os.environ.get(ENV_API_URL, "").strip().rstrip("/")
        token = os.environ.get(ENV_API_TOKEN, "").strip()
        if not base_url:
            raise SundayConfigError(f"{ENV_API_URL} não configurada.")
        if not token:
            raise SundayConfigError(f"{ENV_API_TOKEN} não configurada.")
        return cls(base_url=base_url, token=token)


@dataclass(frozen=True)
class SundayResponse:
    """Resposta já decodificada; 304 vira `not_modified=True` com corpo vazio."""

    status: int
    body: object
    etag: str | None = None

    @property
    def not_modified(self) -> bool:
        return self.status == 304


def urllib_transport(
    method: str,
    url: str,
    body: bytes | None,
    headers: dict[str, str],
    timeout: int,
) -> tuple[int, str, dict[str, str]]:
    """Transporte padrão (stdlib). Erros de rede nunca carregam headers da requisição."""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return (
                response.status,
                response.read().decode("utf-8", "replace"),
                {key.lower(): value for key, value in response.headers.items()},
            )
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        return exc.code, text, {key.lower(): value for key, value in exc.headers.items()}
    except urllib.error.URLError as exc:
        raise SundayHTTPError(f"Sunday API indisponível: {exc.reason}") from exc
    except OSError as exc:
        raise SundayHTTPError(f"Sunday API indisponível: {exc}") from exc


class SundayHttp:
    """Executor de requisições com autenticação, ETag e mapeamento de erros."""

    def __init__(self, config: SundayConfig, transport: Transport | None = None):
        self._config = config
        self._transport = transport or urllib_transport

    def __repr__(self) -> str:  # nunca expõe o token
        return f"SundayHttp(base_url={self._config.base_url!r})"

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        etag: str | None = None,
    ) -> SundayResponse:
        """Executa a chamada e devolve `SundayResponse`; erros HTTP viram exceções.

        - `etag`: enviado como `If-None-Match`; um 304 retorna `not_modified=True`.
        - Retry: SOMENTE para `GET` em 5xx (idempotente). POST/PATCH/DELETE nunca
          são repetidos em silêncio (risco de duplicidade).
        """
        url = f"{self._config.base_url}{path}"
        body: bytes | None = None
        headers = {TOKEN_HEADER: self._config.token}
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if etag:
            headers["If-None-Match"] = etag

        attempts = GET_MAX_ATTEMPTS if method == "GET" else 1
        status, text, response_headers = 0, "", {}
        for attempt in range(attempts):
            status, text, response_headers = self._transport(
                method, url, body, headers, self._config.timeout,
            )
            if method == "GET" and status in GET_RETRY_STATUSES and attempt < attempts - 1:
                time.sleep(GET_RETRY_BASE_DELAY_SECONDS * (2**attempt))
                continue
            break

        if status == 304:
            return SundayResponse(status=304, body=None, etag=etag)
        if status >= 400:
            raise error_for_status(status, method, path, _safe_json(text))
        return SundayResponse(
            status=status,
            body=_safe_json(text),
            etag=response_headers.get("etag"),
        )


def _safe_json(text: str) -> object:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text[:400]
