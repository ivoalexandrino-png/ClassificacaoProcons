"""Backend configurável para a API de quadros (Monday hoje; Sunday na migração).

Toda a comunicação com o quadro passa pelo choke point em ``monday/client.py``.
Este módulo resolve, por variável de ambiente, para qual backend apontar — sem
mudar o comportamento padrão, que continua sendo o **Monday**.

Seleção do backend (``LEGAL_BACKEND``):

- ``monday`` (padrão): usa ``https://api.monday.com/v2`` e o token ``MONDAY_API_TOKEN``.
- ``sunday``: exige ``SUNDAY_API_URL`` (ou o override genérico ``LEGAL_API_URL``);
  o endpoint real do Sunday ainda será calibrado na fase de discovery.

Overrides genéricos (valem para qualquer backend, úteis em testes/canário):
``LEGAL_API_URL``, ``LEGAL_FILE_API_URL``, ``LEGAL_API_VERSION``, ``LEGAL_API_TOKEN``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

BACKEND_MONDAY = "monday"
BACKEND_SUNDAY = "sunday"

ENV_BACKEND = "LEGAL_BACKEND"

# Overrides genéricos (precedem os defaults de cada backend).
ENV_API_URL = "LEGAL_API_URL"
ENV_FILE_API_URL = "LEGAL_FILE_API_URL"
ENV_API_VERSION = "LEGAL_API_VERSION"
ENV_API_TOKEN = "LEGAL_API_TOKEN"

# Monday (comportamento atual — padrão).
MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"
MONDAY_API_VERSION = "2024-10"
ENV_MONDAY_TOKEN = "MONDAY_API_TOKEN"

# Sunday (a calibrar quando tivermos endpoint/token).
ENV_SUNDAY_API_URL = "SUNDAY_API_URL"
ENV_SUNDAY_FILE_API_URL = "SUNDAY_FILE_API_URL"
ENV_SUNDAY_API_VERSION = "SUNDAY_API_VERSION"
ENV_SUNDAY_TOKEN = "SUNDAY_API_TOKEN"


class BackendConfigError(RuntimeError):
    """Configuração de backend ausente ou inválida."""


@dataclass(frozen=True)
class BackendConfig:
    """Parâmetros de transporte resolvidos para o backend ativo."""

    name: str
    api_url: str
    file_api_url: str
    api_version: str | None
    token_env: str


def _env(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


def get_backend_name() -> str:
    return (os.environ.get(ENV_BACKEND, BACKEND_MONDAY).strip().casefold()) or BACKEND_MONDAY


def get_backend_config() -> BackendConfig:
    """Resolve o backend ativo a partir do ambiente (padrão: Monday)."""
    name = get_backend_name()

    if name == BACKEND_MONDAY:
        return BackendConfig(
            name=name,
            api_url=_env(ENV_API_URL) or MONDAY_API_URL,
            file_api_url=_env(ENV_FILE_API_URL) or MONDAY_FILE_API_URL,
            api_version=_env(ENV_API_VERSION) or MONDAY_API_VERSION,
            token_env=ENV_MONDAY_TOKEN,
        )

    if name == BACKEND_SUNDAY:
        api_url = _env(ENV_API_URL) or _env(ENV_SUNDAY_API_URL)
        if not api_url:
            raise BackendConfigError(
                "LEGAL_BACKEND=sunday exige SUNDAY_API_URL (ou LEGAL_API_URL). "
                "O endpoint do Sunday ainda não foi calibrado.",
            )
        file_api_url = (
            _env(ENV_FILE_API_URL) or _env(ENV_SUNDAY_FILE_API_URL) or f"{api_url.rstrip('/')}/file"
        )
        return BackendConfig(
            name=name,
            api_url=api_url,
            file_api_url=file_api_url,
            api_version=_env(ENV_API_VERSION) or _env(ENV_SUNDAY_API_VERSION),
            token_env=ENV_SUNDAY_TOKEN,
        )

    raise BackendConfigError(
        f"LEGAL_BACKEND inválido: {name!r} (use '{BACKEND_MONDAY}' ou '{BACKEND_SUNDAY}').",
    )


def get_api_token() -> str | None:
    """Token do backend ativo.

    Preferência: variável específica do backend → ``LEGAL_API_TOKEN`` →
    ``MONDAY_API_TOKEN`` (fallback ao segredo compartilhado no cutover).
    """
    config = get_backend_config()
    return _env(config.token_env) or _env(ENV_API_TOKEN) or _env(ENV_MONDAY_TOKEN)


__all__ = [
    "BACKEND_MONDAY",
    "BACKEND_SUNDAY",
    "BackendConfig",
    "BackendConfigError",
    "get_api_token",
    "get_backend_config",
    "get_backend_name",
]
