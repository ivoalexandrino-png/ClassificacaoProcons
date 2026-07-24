"""Modelos de credenciais de portais."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PortalCredentials:
    """Credenciais para login em portal Procon/Proconsumidor."""

    source_id: str
    elemento: str
    login: str
    password: str
    portal_url: str | None = None
    monday_item_id: str | None = None
