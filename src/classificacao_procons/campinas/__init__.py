"""Integração com Procon Campinas."""

from classificacao_procons.campinas.deadlines import calculate_campinas_deadlines
from classificacao_procons.campinas.email_parser import (
    CAMPINAS_SENDER,
    CAMPINAS_STATE_LABEL,
    ParsedCampinasEmail,
    is_campinas_notification,
    parse_campinas_notification_body,
)
from classificacao_procons.campinas.portal import (
    CampinasPortalError,
    CampinasPortalOptions,
    fetch_campinas_complaint,
)

__all__ = [
    "CAMPINAS_SENDER",
    "CAMPINAS_STATE_LABEL",
    "CampinasPortalError",
    "CampinasPortalOptions",
    "ParsedCampinasEmail",
    "calculate_campinas_deadlines",
    "fetch_campinas_complaint",
    "is_campinas_notification",
    "parse_campinas_notification_body",
]
