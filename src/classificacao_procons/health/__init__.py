"""Monitoramento de SLA da automação Procon."""

from classificacao_procons.health.procon_sla import (
    ProconSlaReport,
    StaleUnreadNotification,
    build_procon_sla_report,
    check_github_workflow_freshness,
)

__all__ = [
    "ProconSlaReport",
    "StaleUnreadNotification",
    "build_procon_sla_report",
    "check_github_workflow_freshness",
]
