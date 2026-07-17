"""Testes de autenticação Google."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from classificacao_procons.google_auth import (
    GoogleAuthError,
    _normalize_auth_code,
    get_authorization_url,
    materialize_credentials_from_env,
    save_token_from_code,
)


@pytest.fixture
def oauth_files(tmp_path: Path) -> tuple[Path, Path]:
    credentials = tmp_path / "gmail-oauth.json"
    credentials.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "client-id",
                    "client_secret": "client-secret",
                    "redirect_uris": ["http://localhost"],
                },
            },
        ),
        encoding="utf-8",
    )
    token = tmp_path / "gmail-token.json"
    return credentials, token


def test_get_authorization_url_remote_should_not_create_pending_file(
    oauth_files: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    credentials, _ = oauth_files
    pending = tmp_path / "oauth-pending.json"

    with patch("classificacao_procons.google_auth._create_oauth_flow") as create_flow:
        flow = MagicMock()
        flow.authorization_url.return_value = ("https://example.com/auth", "state")
        create_flow.return_value = flow

        url = get_authorization_url(
            credentials_path=str(credentials),
            remote=True,
        )

    assert url == "https://example.com/auth"
    create_flow.assert_called_once_with(credentials_path=str(credentials), remote=True)
    assert not pending.exists()


def test_save_token_from_code_remote_should_skip_pending_file(
    oauth_files: tuple[Path, Path],
) -> None:
    credentials, token = oauth_files

    with patch("classificacao_procons.google_auth._create_oauth_flow") as create_flow:
        flow = MagicMock()
        flow.credentials.to_json.return_value = '{"token":"ok"}'
        create_flow.return_value = flow

        save_token_from_code(
            code="4/0ABC",
            credentials_path=str(credentials),
            token_path=str(token),
            remote=True,
        )

    create_flow.assert_called_once_with(credentials_path=str(credentials), remote=True)
    flow.fetch_token.assert_called_once_with(code="4/0ABC")
    assert token.read_text(encoding="utf-8") == '{"token":"ok"}'


def test_normalize_auth_code_should_strip_code_prefix_and_leading_equals() -> None:
    assert _normalize_auth_code("code=4/0ABC") == "4/0ABC"
    assert _normalize_auth_code("=4/0ABC") == "4/0ABC"


def test_save_token_from_code_should_normalize_malformed_paste(
    oauth_files: tuple[Path, Path],
) -> None:
    credentials, token = oauth_files

    with patch("classificacao_procons.google_auth._create_oauth_flow") as create_flow:
        flow = MagicMock()
        flow.credentials.to_json.return_value = '{"token":"ok"}'
        create_flow.return_value = flow

        save_token_from_code(
            code="=4/0ABC",
            credentials_path=str(credentials),
            token_path=str(token),
            remote=True,
        )

    flow.fetch_token.assert_called_once_with(code="4/0ABC")


def test_save_token_from_code_should_raise_when_pending_missing_and_not_remote(
    oauth_files: tuple[Path, Path],
) -> None:
    credentials, token = oauth_files

    with pytest.raises(GoogleAuthError, match="Link expirado"):
        save_token_from_code(
            code="4/0ABC",
            credentials_path=str(credentials),
            token_path=str(token),
            remote=False,
        )


class TestMaterializeCredentialsFromEnv:
    def test_should_write_files_from_env_when_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        credentials_path = tmp_path / "creds" / "gmail-oauth.json"
        token_path = tmp_path / "creds" / "gmail-token.json"
        monkeypatch.setenv("GMAIL_OAUTH_JSON", '{"installed": {"client_id": "abc"}}')
        monkeypatch.setenv("GMAIL_TOKEN_JSON", '{"token": "xyz", "scopes": []}')

        materialize_credentials_from_env(
            credentials_path=str(credentials_path),
            token_path=str(token_path),
        )

        assert json.loads(credentials_path.read_text()) == {"installed": {"client_id": "abc"}}
        assert json.loads(token_path.read_text()) == {"token": "xyz", "scopes": []}

    def test_should_not_overwrite_existing_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        token_path = tmp_path / "gmail-token.json"
        token_path.write_text('{"token": "original"}', encoding="utf-8")
        monkeypatch.setenv("GMAIL_TOKEN_JSON", '{"token": "novo"}')

        materialize_credentials_from_env(
            credentials_path=str(tmp_path / "gmail-oauth.json"),
            token_path=str(token_path),
        )

        assert json.loads(token_path.read_text()) == {"token": "original"}

    def test_should_ignore_invalid_json_in_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        token_path = tmp_path / "gmail-token.json"
        monkeypatch.setenv("GMAIL_TOKEN_JSON", "não é json")

        materialize_credentials_from_env(
            credentials_path=str(tmp_path / "gmail-oauth.json"),
            token_path=str(token_path),
        )

        assert not token_path.exists()

    def test_should_do_nothing_when_env_is_empty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("GMAIL_OAUTH_JSON", raising=False)
        monkeypatch.delenv("GMAIL_TOKEN_JSON", raising=False)
        token_path = tmp_path / "gmail-token.json"

        materialize_credentials_from_env(
            credentials_path=str(tmp_path / "gmail-oauth.json"),
            token_path=str(token_path),
        )

        assert not token_path.exists()
