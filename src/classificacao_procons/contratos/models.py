"""Modelos compartilhados do módulo de contratos."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ControleAssinaturasItem:
    item_id: str
    name: str
    status: str | None
    tipo: str | None
    signature_link: str | None
    related_contract_item_ids: tuple[str, ...] = ()
