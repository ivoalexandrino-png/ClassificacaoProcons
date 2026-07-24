"""Módulo de integração com e-mail."""

from classificacao_procons.email.gmail import (
    DEFAULT_GMAIL_QUERY,
    GmailClientError,
    GmailProconFetcher,
)
from classificacao_procons.email.parser import (
    PROCON_PA_SUBJECT_PREFIX,
    PROCON_PORTAL_LOGIN_URL,
    PROCON_SP_SENDER,
    PROCON_SP_SUBJECT,
    ProconEmailParseError,
    extract_administrative_process_number,
    is_procon_cip_notification,
    is_procon_notification,
    is_procon_pa_notification,
    parse_procon_notification_body,
)

__all__ = [
    "DEFAULT_GMAIL_QUERY",
    "GmailClientError",
    "GmailProconFetcher",
    "PROCON_PA_SUBJECT_PREFIX",
    "PROCON_PORTAL_LOGIN_URL",
    "PROCON_SP_SENDER",
    "PROCON_SP_SUBJECT",
    "ProconEmailParseError",
    "extract_administrative_process_number",
    "is_procon_cip_notification",
    "is_procon_notification",
    "is_procon_pa_notification",
    "parse_procon_notification_body",
]
