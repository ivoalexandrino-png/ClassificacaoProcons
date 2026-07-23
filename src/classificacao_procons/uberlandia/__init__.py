"""Integração com Procon Uberlândia (Fale Procon)."""

from classificacao_procons.uberlandia.deadlines import calculate_uberlandia_deadlines
from classificacao_procons.uberlandia.email_parser import (
    UBERLANDIA_PORTAL_URL,
    UBERLANDIA_SENDER,
    UBERLANDIA_STATE_LABEL,
    ParsedUberlandiaEmail,
    UberlandiaEmailParseError,
    is_uberlandia_notification,
    parse_uberlandia_notification_body,
)
from classificacao_procons.uberlandia.portal import (
    UberlandiaPortalError,
    UberlandiaPortalOptions,
    fetch_uberlandia_complaint,
)

__all__ = [
    "UBERLANDIA_PORTAL_URL",
    "UBERLANDIA_SENDER",
    "UBERLANDIA_STATE_LABEL",
    "ParsedUberlandiaEmail",
    "UberlandiaEmailParseError",
    "UberlandiaPortalError",
    "UberlandiaPortalOptions",
    "calculate_uberlandia_deadlines",
    "fetch_uberlandia_complaint",
    "is_uberlandia_notification",
    "parse_uberlandia_notification_body",
]
