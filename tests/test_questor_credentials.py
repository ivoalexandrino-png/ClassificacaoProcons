"""Testes da leitura de credenciais do Questor no board Acessos do Monday."""

from unittest.mock import patch

import pytest

from classificacao_procons.questor.credentials import (
    QuestorCredentialsError,
    resolve_questor_credentials,
)

BOARD_PAYLOAD = {
    "boards": [
        {
            "columns": [
                {"id": "c_login", "title": "Login", "type": "text"},
                {"id": "c_senha", "title": "Senha", "type": "text"},
                {"id": "c_link", "title": "Link", "type": "link"},
            ],
            "groups": [
                {
                    "items_page": {
                        "items": [
                            {
                                "id": "111",
                                "name": "Procon SP",
                                "column_values": [
                                    {"id": "c_login", "text": "user-sp", "value": None},
                                    {"id": "c_senha", "text": "pass-sp", "value": None},
                                ],
                            },
                            {
                                "id": "222",
                                "name": "Questor - Certidões - Ivo",
                                "column_values": [
                                    {"id": "c_login", "text": "questor-user", "value": None},
                                    {"id": "c_senha", "text": "questor-pass", "value": None},
                                    {"id": "c_link", "text": "", "value": None},
                                ],
                            },
                        ],
                    },
                },
            ],
        },
    ],
}


def test_should_resolve_designated_ivo_item_by_default() -> None:
    with patch(
        "classificacao_procons.questor.credentials._graphql_request",
        return_value=BOARD_PAYLOAD,
    ):
        cred = resolve_questor_credentials(api_token="tok", board_id="7591024769")

    assert cred.login == "questor-user"
    assert cred.password == "questor-pass"
    assert cred.elemento == "Questor - Certidões - Ivo"
    assert cred.monday_item_id == "222"


def test_should_match_item_by_explicit_name() -> None:
    with patch(
        "classificacao_procons.questor.credentials._graphql_request",
        return_value=BOARD_PAYLOAD,
    ):
        cred = resolve_questor_credentials(
            api_token="tok",
            item_name="Questor - Certidões - Ivo",
        )
    assert cred.monday_item_id == "222"


def test_should_raise_when_item_missing() -> None:
    empty = {"boards": [{"columns": [], "groups": []}]}
    with patch(
        "classificacao_procons.questor.credentials._graphql_request",
        return_value=empty,
    ):
        with pytest.raises(QuestorCredentialsError, match="não encontrado"):
            resolve_questor_credentials(api_token="tok")


def test_should_raise_without_token() -> None:
    with patch(
        "classificacao_procons.questor.credentials.get_api_token_from_env",
        return_value=None,
    ):
        with pytest.raises(QuestorCredentialsError, match="MONDAY_API_TOKEN"):
            resolve_questor_credentials()
