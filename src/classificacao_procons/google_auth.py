"""Escopos e credenciais Google (Gmail + Drive)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

GOOGLE_SCOPES = [
    GMAIL_READONLY_SCOPE,
    GMAIL_MODIFY_SCOPE,
    DRIVE_FILE_SCOPE,
    DRIVE_READONLY_SCOPE,
]

DEFAULT_CREDENTIALS_PATH = "credentials/gmail-oauth.json"
DEFAULT_TOKEN_PATH = "credentials/gmail-token.json"
PENDING_AUTH_PATH = "credentials/oauth-pending.json"
LOCALHOST_REDIRECT_URI = "http://localhost"

ENV_OAUTH_CLIENT_JSON = "GMAIL_OAUTH_JSON"
ENV_TOKEN_JSON = "GMAIL_TOKEN_JSON"

DEFAULT_DRIVE_PARENT_FOLDER_ID = "1Ly7WYusnzXWSMb-T3a6TNCQSSduvB4Wh"


class GoogleAuthError(RuntimeError):
    """Erro de autenticação Google."""


def _write_credential_file(path: str, content: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.chmod(path, 0o600)


def materialize_credentials_from_env(
    *,
    credentials_path: str = DEFAULT_CREDENTIALS_PATH,
    token_path: str = DEFAULT_TOKEN_PATH,
) -> None:
    """Cria os arquivos de credenciais a partir das variáveis de ambiente.

    Em ambientes sem a pasta ``credentials/`` (Cloud Agents, Cloud Run, CI),
    os secrets ``GMAIL_OAUTH_JSON`` e ``GMAIL_TOKEN_JSON`` chegam como
    variáveis de ambiente; este helper os grava em disco no primeiro uso.
    Arquivos já existentes nunca são sobrescritos.
    """
    for env_name, path in (
        (ENV_OAUTH_CLIENT_JSON, credentials_path),
        (ENV_TOKEN_JSON, token_path),
    ):
        if os.path.exists(path):
            continue
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            continue
        try:
            json.loads(raw)
        except json.JSONDecodeError:
            continue
        _write_credential_file(path, raw)


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
        raise GoogleAuthError(
            "Link expirado. Gere um novo com: procon-email auth",
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _create_oauth_flow(
    *,
    credentials_path: str,
    remote: bool,
) -> InstalledAppFlow:
    if not os.path.exists(credentials_path):
        raise GoogleAuthError(f"Arquivo não encontrado: {credentials_path}")

    flow = InstalledAppFlow.from_client_secrets_file(
        credentials_path,
        scopes=GOOGLE_SCOPES,
        autogenerate_code_verifier=not remote,
    )
    flow.redirect_uri = LOCALHOST_REDIRECT_URI
    return flow


def get_authorization_url(
    *,
    credentials_path: str = DEFAULT_CREDENTIALS_PATH,
    remote: bool = False,
) -> str:
    """Gera link para autorizar Gmail + Drive."""
    flow = _create_oauth_flow(credentials_path=credentials_path, remote=remote)
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")
    if not remote:
        _save_pending_auth(flow, state)
    return auth_url


def _normalize_auth_code(code: str) -> str:
    """Remove prefixos comuns ao colar da barra de endereço (ex.: code= ou =)."""
    cleaned = code.strip()
    if cleaned.lower().startswith("code="):
        cleaned = cleaned[5:]
    return cleaned.lstrip("=").strip()


def save_token_from_code(
    *,
    code: str,
    credentials_path: str = DEFAULT_CREDENTIALS_PATH,
    token_path: str = DEFAULT_TOKEN_PATH,
    remote: bool = False,
) -> None:
    """Salva token após usuário colar o código de autorização."""
    pending_path = Path(PENDING_AUTH_PATH)
    normalized_code = _normalize_auth_code(code)

    if remote or not pending_path.exists():
        if not remote:
            raise GoogleAuthError(
                "Link expirado. Gere um novo com: procon-email auth",
            )
        flow = _create_oauth_flow(credentials_path=credentials_path, remote=True)
        flow.fetch_token(code=normalized_code)
    else:
        pending = _load_pending_auth()
        flow = _create_oauth_flow(credentials_path=credentials_path, remote=False)
        flow.redirect_uri = pending["redirect_uri"]
        flow.code_verifier = pending["code_verifier"]
        flow.fetch_token(code=normalized_code)
        pending_path.unlink(missing_ok=True)

    os.makedirs(os.path.dirname(token_path) or ".", exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as token_file:
        token_file.write(flow.credentials.to_json())


def load_credentials(token_path: str = DEFAULT_TOKEN_PATH) -> Credentials:
    """Carrega credenciais salvas."""
    materialize_credentials_from_env(token_path=token_path)
    if not os.path.exists(token_path):
        raise GoogleAuthError("Google ainda não conectado. Rode: procon-email auth")

    credentials = Credentials.from_authorized_user_file(token_path, GOOGLE_SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        with open(token_path, "w", encoding="utf-8") as token_file:
            token_file.write(credentials.to_json())

    if not credentials.valid:
        raise GoogleAuthError("Token inválido. Rode novamente: procon-email auth")

    return credentials


def has_valid_token(token_path: str = DEFAULT_TOKEN_PATH) -> bool:
    """Verifica se Gmail e Drive estão autorizados."""
    materialize_credentials_from_env(token_path=token_path)
    if not os.path.exists(token_path):
        return False

    try:
        data = json.loads(Path(token_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    scopes = set(data.get("scopes", []))
    required = {
        DRIVE_FILE_SCOPE,
        DRIVE_READONLY_SCOPE,
        GMAIL_READONLY_SCOPE,
    }
    if not required.issubset(scopes):
        return False

    try:
        credentials = load_credentials(token_path)
    except GoogleAuthError:
        return False
    return credentials.valid


def has_drive_access(token_path: str = DEFAULT_TOKEN_PATH) -> bool:
    """Verifica se o token inclui permissão do Drive."""
    if not os.path.exists(token_path):
        return False
    data = json.loads(Path(token_path).read_text(encoding="utf-8"))
    scopes = set(data.get("scopes", []))
    return DRIVE_FILE_SCOPE in scopes and DRIVE_READONLY_SCOPE in scopes


def has_gmail_modify_access(token_path: str = DEFAULT_TOKEN_PATH) -> bool:
    """Verifica se o token pode marcar e-mails como lidos."""
    if not os.path.exists(token_path):
        return False
    data = json.loads(Path(token_path).read_text(encoding="utf-8"))
    return GMAIL_MODIFY_SCOPE in set(data.get("scopes", []))
