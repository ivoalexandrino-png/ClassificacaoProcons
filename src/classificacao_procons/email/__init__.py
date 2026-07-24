"""Módulo de integração com e-mail."""

from classificacao_procons.email.parser import (
    PROCON_PORTAL_LOGIN_URL,
    PROCON_SP_SENDER,
    PROCON_SP_SUBJECT,
    ProconEmailParseError,
    is_procon_cip_notification,
    parse_procon_notification_body,
)

__all__ = [
    "PROCON_PORTAL_LOGIN_URL",
    "PROCON_SP_SENDER",
    "PROCON_SP_SUBJECT",
    "ProconEmailParseError",
    "is_procon_cip_notification",
    "parse_procon_notification_body",
]
