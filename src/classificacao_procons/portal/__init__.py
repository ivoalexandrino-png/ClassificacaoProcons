"""Integração com o portal Procon-SP."""

from classificacao_procons.portal.client import (
    PortalFetchOptions,
    ProconPortalError,
    fetch_complaint,
)

__all__ = [
    "PortalFetchOptions",
    "ProconPortalError",
    "fetch_complaint",
]
