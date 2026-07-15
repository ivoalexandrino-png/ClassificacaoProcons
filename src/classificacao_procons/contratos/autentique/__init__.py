"""Cliente e webhooks do Autentique."""

from classificacao_procons.contratos.autentique.client import (
    AutentiqueClientError,
    AutentiqueDocument,
    download_file,
    fetch_document,
    get_api_token_from_env,
)
from classificacao_procons.contratos.autentique.webhook import (
    parse_webhook_event,
    verify_webhook_signature,
)

__all__ = [
    "AutentiqueClientError",
    "AutentiqueDocument",
    "download_file",
    "fetch_document",
    "get_api_token_from_env",
    "parse_webhook_event",
    "verify_webhook_signature",
]
