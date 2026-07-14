"""Compatibilidade — use classificacao_procons.google_auth."""

from classificacao_procons.google_auth import (
    DEFAULT_CREDENTIALS_PATH,
    DEFAULT_TOKEN_PATH,
    GMAIL_READONLY_SCOPE,
    GoogleAuthError,
    get_authorization_url,
    has_valid_token,
    save_token_from_code,
)

GmailClientError = GoogleAuthError

__all__ = [
    "DEFAULT_CREDENTIALS_PATH",
    "DEFAULT_TOKEN_PATH",
    "GMAIL_READONLY_SCOPE",
    "GmailClientError",
    "get_authorization_url",
    "has_valid_token",
    "save_token_from_code",
]
