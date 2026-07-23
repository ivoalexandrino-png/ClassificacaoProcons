"""Provedor de código 2FA lendo o e-mail de verificação do tribunal via Gmail.

O e-SAJ envia um código de acesso ao e-mail cadastrado. Este provedor busca a
mensagem mais recente do tribunal na caixa autorizada e extrai o código.
"""

from __future__ import annotations

import base64
import re
import time

from googleapiclient.discovery import build

from classificacao_procons.google_auth import load_credentials

# Assunto/remetente das mensagens de código do e-SAJ/TJSP.
_TOKEN_QUERY = 'from:tjsp.jus.br (código OR codigo OR token OR acesso OR verificação)'
_CODE_PATTERN = re.compile(r"\b(\d{4,8})\b")
_POLL_ATTEMPTS = 10
_POLL_INTERVAL_SECONDS = 6


def _message_text(payload: dict) -> str:
    if payload.get("mimeType", "").startswith("text/") and payload.get("body", {}).get("data"):
        raw = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        return re.sub(r"<[^>]+>", " ", raw)
    for part in payload.get("parts", []) or []:
        text = _message_text(part)
        if text:
            return text
    return ""


def gmail_token_provider(
    _login: str,
    *,
    token_path: str = "credentials/gmail-token.json",
    since_epoch: int | None = None,
) -> str | None:
    """Busca o código 2FA mais recente do e-SAJ na caixa autorizada.

    Faz polling (o e-mail leva alguns segundos para chegar). ``since_epoch``
    limita a mensagens recebidas após o início do login, evitando reusar um
    código antigo.
    """
    credentials = load_credentials(token_path)
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    cutoff = since_epoch or int(time.time())

    for _ in range(_POLL_ATTEMPTS):
        response = (
            service.users()
            .messages()
            .list(userId="me", q=_TOKEN_QUERY, maxResults=5)
            .execute()
        )
        for ref in response.get("messages", []):
            message = (
                service.users()
                .messages()
                .get(userId="me", id=ref["id"], format="full")
                .execute()
            )
            if int(message.get("internalDate", "0")) // 1000 < cutoff:
                continue
            text = f"{message.get('snippet', '')} {_message_text(message.get('payload', {}))}"
            match = _CODE_PATTERN.search(text)
            if match:
                return match.group(1)
        time.sleep(_POLL_INTERVAL_SECONDS)
    return None
