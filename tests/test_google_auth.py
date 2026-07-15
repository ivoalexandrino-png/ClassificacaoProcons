"""Testes de autenticação Google."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from classificacao_procons.google_auth import (
    GoogleAuthError,
    get_authorization_url,
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
