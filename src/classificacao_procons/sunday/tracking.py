"""Tipos de rastreabilidade Monday → Sunday para a FUTURA camada de migração.

Mantidos fora do `SundayClient` de propósito: o client é genérico e não conhece o
Monday. A migração (Fase 2) persistirá estes registros em
`data/monday-sunday-map.json` e na coluna "Monday ID" dos boards migrados.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MigrationStatus = Literal["pending", "migrated", "skipped", "error"]


@dataclass(frozen=True)
class MigrationRecord:
    """Uma linha do de-para de itens entre os dois sistemas."""

    monday_board_id: str
    monday_item_id: str
    sunday_board_id: str | None = None
    sunday_item_id: str | None = None
    domain: str | None = None
    migration_status: MigrationStatus = "pending"
    migrated_at: str | None = None
    error: str | None = None
