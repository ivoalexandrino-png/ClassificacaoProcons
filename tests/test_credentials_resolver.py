"""Testes do resolver de credenciais."""

from unittest.mock import patch

import pytest

from classificacao_procons.credentials import (
    CredentialsError,
    resolve_portal_credentials,
)
from classificacao_procons.credentials.monday_board import PortalCredentialsRecord


class TestCredentialsResolver:
    def test_should_raise_when_source_is_unknown(self) -> None:
        with pytest.raises(CredentialsError, match="desconhecida"):
            resolve_portal_credentials("invalid", api_token="token")

    @patch("classificacao_procons.credentials.resolver.fetch_procon_credentials_records")
    def test_should_resolve_credentials_for_proconsumidor(self, fetch_mock) -> None:
        fetch_mock.return_value = [
            PortalCredentialsRecord(
                elemento="Proconsumidor",
                login="40712473807",
                password="secret-value",
                portal_url=None,
                monday_item_id="99",
            ),
        ]

        credentials = resolve_portal_credentials("proconsumidor", api_token="token-test")

        assert credentials.source_id == "proconsumidor"
        assert credentials.elemento == "Proconsumidor"
        assert credentials.login == "40712473807"
        assert credentials.password == "secret-value"
        assert credentials.portal_url == "https://proconsumidor.mj.gov.br/#/login"
        assert credentials.monday_item_id == "99"

    @patch("classificacao_procons.credentials.resolver.fetch_procon_credentials_records")
    def test_should_raise_when_credentials_not_found(self, fetch_mock) -> None:
        fetch_mock.return_value = []

        with pytest.raises(CredentialsError, match="não encontradas"):
            resolve_portal_credentials("campinas", api_token="token-test")
