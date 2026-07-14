"""Autorização simplificada do Gmail (fluxo manual para iniciantes)."""

from __future__ import annotations

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from classificacao_procons.email.gmail import GMAIL_READONLY_SCOPE, GmailClientError

DEFAULT_CREDENTIALS_PATH = "credentials/gmail-oauth.json"
DEFAULT_TOKEN_PATH = "credentials/gmail-token.json"


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
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
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

    flow = InstalledAppFlow.from_client_secrets_file(
        credentials_path,
        scopes=[GMAIL_READONLY_SCOPE],
    )
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    flow.fetch_token(code=code.strip())
    credentials = flow.credentials

    os.makedirs(os.path.dirname(token_path) or ".", exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as token_file:
        token_file.write(credentials.to_json())


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
