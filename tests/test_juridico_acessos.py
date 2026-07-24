"""Testes da resolução de credenciais de portais (quadro Acessos)."""

from unittest.mock import patch

import pytest

from classificacao_procons.juridico import acessos
from classificacao_procons.juridico.acessos import (
    AcessosError,
    PortalCredential,
    get_tribunal_credential,
    list_portal_credentials,
)

_BOARD_RESPONSE = {
    "boards": [
        {
            "items_page": {
                "items": [
                    {
                        "name": "TJ-SP",
                        "group": {"title": "TJ's"},
                        "column_values": [
                            {"column": {"title": "Sistema"}, "text": "E-SAJ"},
                            {"column": {"title": "Login"}, "text": "40712473807"},
                            {"column": {"title": "Senha"}, "text": "segredo-sp"},
                        ],
                    },
                    {
                        "name": "TJ- AM",
                        "group": {"title": "TJ's"},
                        "column_values": [
                            {"column": {"title": "Sistema"}, "text": "PROJUDI"},
                            {"column": {"title": "Login"}, "text": "40712473807"},
                            {"column": {"title": "Senha"}, "text": "segredo-am"},
                        ],
                    },
                    {
                        "name": "Sem senha",
                        "group": {"title": "TJ's"},
                        "column_values": [
                            {"column": {"title": "Login"}, "text": "so-login"},
                            {"column": {"title": "Senha"}, "text": ""},
                        ],
                    },
                ],
            },
        },
    ],
}


@pytest.fixture(autouse=True)
def _board_id(monkeypatch):
    monkeypatch.setenv("MONDAY_ACESSOS_BOARD_ID", "999")


class TestListPortalCredentials:
    def test_should_list_credentials_with_login_and_password(self) -> None:
        with patch.object(acessos, "_graphql_request", return_value=_BOARD_RESPONSE):
            creds = list_portal_credentials(api_token="token")

        assert len(creds) == 2  # item sem senha é ignorado
        assert creds[0] == PortalCredential(
            tribunal="TJ-SP",
            system="E-SAJ",
            login="40712473807",
            password="segredo-sp",
        )

    def test_should_raise_without_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MONDAY_API_TOKEN", raising=False)
        with pytest.raises(AcessosError, match="MONDAY_API_TOKEN"):
            list_portal_credentials()

    def test_repr_should_not_leak_password(self) -> None:
        cred = PortalCredential("TJ-SP", "E-SAJ", "login", "top-secret")
        assert "top-secret" not in repr(cred)
        assert "***" in repr(cred)


class TestGetTribunalCredential:
    def test_should_match_acronym_ignoring_dashes_and_spaces(self) -> None:
        with patch.object(acessos, "_graphql_request", return_value=_BOARD_RESPONSE):
            assert get_tribunal_credential("TJSP", api_token="token").login == "40712473807"
            # "TJ- AM" (com espaço/hífen) casa com "TJAM"
            assert get_tribunal_credential("TJAM", api_token="token").system == "PROJUDI"

    def test_should_return_none_when_no_credential(self) -> None:
        with patch.object(acessos, "_graphql_request", return_value=_BOARD_RESPONSE):
            assert get_tribunal_credential("TJPR", api_token="token") is None
