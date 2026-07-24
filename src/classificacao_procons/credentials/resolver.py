"""Resolução de credenciais por source_id."""

from __future__ import annotations

from classificacao_procons.credentials.mapping import SOURCE_ELEMENTO_ALIASES
from classificacao_procons.credentials.models import PortalCredentials
from classificacao_procons.credentials.monday_board import (
    fetch_procon_credentials_records,
    find_credentials_for_source,
    to_portal_credentials,
)
from classificacao_procons.monday.client import get_api_token_from_env


class CredentialsError(RuntimeError):
    """Credenciais de portal não encontradas ou inválidas."""


def resolve_portal_credentials(
    source_id: str,
    *,
    api_token: str | None = None,
) -> PortalCredentials:
    """Busca login/senha do portal no board Acessos do Monday."""
    normalized_source = source_id.strip().lower()
    if normalized_source not in SOURCE_ELEMENTO_ALIASES:
        raise CredentialsError(f'Fonte de credenciais desconhecida: "{source_id}".')

    token = api_token or get_api_token_from_env()
    if not token:
        raise CredentialsError("MONDAY_API_TOKEN não configurada para buscar credenciais.")

    records = fetch_procon_credentials_records(api_token=token)
    record = find_credentials_for_source(records, source_id=normalized_source)
    if record is None:
        raise CredentialsError(
            f'Credenciais não encontradas no Monday para a fonte "{normalized_source}".',
        )

    return to_portal_credentials(record, source_id=normalized_source)


def list_procon_portal_credentials(
    *,
    api_token: str | None = None,
) -> list[PortalCredentials]:
    """Lista credenciais do grupo Procon sem expor senhas em logs externos."""
    token = api_token or get_api_token_from_env()
    if not token:
        raise CredentialsError("MONDAY_API_TOKEN não configurada para buscar credenciais.")

    records = fetch_procon_credentials_records(api_token=token)
    credentials: list[PortalCredentials] = []
    for source_id in SOURCE_ELEMENTO_ALIASES:
        record = find_credentials_for_source(records, source_id=source_id)
        if record is not None:
            credentials.append(to_portal_credentials(record, source_id=source_id))
    return credentials
