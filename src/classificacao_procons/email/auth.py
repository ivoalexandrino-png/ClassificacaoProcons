"""Autorização simplificada do Gmail (fluxo manual para iniciantes)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from classificacao_procons.email.gmail import GMAIL_READONLY_SCOPE, GmailClientError

DEFAULT_CREDENTIALS_PATH = "credentials/gmail-oauth.json"
DEFAULT_TOKEN_PATH = "credentials/gmail-token.json"
PENDING_AUTH_PATH = "credentials/oauth-pending.json"
LOCALHOST_REDIRECT_URI = "http://localhost"


def _save_pending_auth(flow: InstalledAppFlow, state: str) -> None:
    pending = {
        "state": state,
        "redirect_uri": flow.redirect_uri,
        "code_verifier": flow.code_verifier,
    }
    path = Path(PENDING_AUTH_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pending), encoding="utf-8")


def _load_pending_auth() -> dict[str, str]:
    path = Path(PENDING_AUTH_PATH)
    if not path.exists():
        raise GmailClientError(
            "Link de autorização expirado. Peça um link novo com: procon-email auth",
        )
    return json.loads(path.read_text(encoding="utf-8"))


def get_authorization_url(
    *,
    credentials_path: str = DEFAULT_CREDENTIALS_PATH,
) -> str:
    """Gera o link que o usuário deve abrir no navegador."""
    if not os.path.exists(credentials_path):
        raise GmailClientError(f"Arquivo não encontrado: {credentials_path}")

    flow = InstalledAppFlow.from_client_secrets_file(
        credentials_path,
        scopes=[GMAIL_READONLY_SCOPE],
    )
    flow.redirect_uri = LOCALHOST_REDIRECT_URI
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")
    _save_pending_auth(flow, state)
    return auth_url


def save_token_from_code(
    *,
    code: str,
    credentials_path: str = DEFAULT_CREDENTIALS_PATH,
    token_path: str = DEFAULT_TOKEN_PATH,
) -> None:
    """Salva o token após o usuário colar o código de autorização."""
    if not os.path.exists(credentials_path):
        raise GmailClientError(f"Arquivo não encontrado: {credentials_path}")

    pending = _load_pending_auth()
    flow = InstalledAppFlow.from_client_secrets_file(
        credentials_path,
        scopes=[GMAIL_READONLY_SCOPE],
    )
    flow.redirect_uri = pending["redirect_uri"]
    flow.code_verifier = pending["code_verifier"]
    flow.fetch_token(code=code.strip())
    credentials = flow.credentials

    os.makedirs(os.path.dirname(token_path) or ".", exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as token_file:
        token_file.write(credentials.to_json())

    Path(PENDING_AUTH_PATH).unlink(missing_ok=True)


def has_valid_token(token_path: str = DEFAULT_TOKEN_PATH) -> bool:
    """Verifica se já existe um token válido salvo."""
    if not os.path.exists(token_path):
        return False
    credentials = Credentials.from_authorized_user_file(
        token_path,
        [GMAIL_READONLY_SCOPE],
    )
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        with open(token_path, "w", encoding="utf-8") as token_file:
            token_file.write(credentials.to_json())
    return bool(credentials and credentials.valid)
