"""Integração com Proconsumidor (Sistema Nacional)."""

from classificacao_procons.proconsumidor.email_parser import (
    PROCONSUMIDOR_SENDER,
    PROCONSUMIDOR_SUBJECT,
    extract_proconsumidor_complaint_number,
    extract_proconsumidor_regional_org,
    extract_proconsumidor_state,
    is_proconsumidor_notification,
    parse_proconsumidor_notification_body,
)
from classificacao_procons.proconsumidor.portal import (
    ProconsumidorPortalError,
    ProconsumidorPortalOptions,
    fetch_proconsumidor_complaint,
)

__all__ = [
    "PROCONSUMIDOR_SENDER",
    "PROCONSUMIDOR_SUBJECT",
    "ProconsumidorPortalError",
    "ProconsumidorPortalOptions",
    "extract_proconsumidor_complaint_number",
    "extract_proconsumidor_regional_org",
    "extract_proconsumidor_state",
    "fetch_proconsumidor_complaint",
    "is_proconsumidor_notification",
    "parse_proconsumidor_notification_body",
]
