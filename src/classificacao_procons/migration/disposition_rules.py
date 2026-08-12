"""Registro de regras de disposição por board (engine canônica única)."""

from __future__ import annotations

from classificacao_procons.migration.audiencias import (
    AUDIENCIAS_MONDAY_BOARD_ID,
    audiencias_rules,
)
from classificacao_procons.migration.board_disposition import BoardRules
from classificacao_procons.migration.mappings import WAVE1_TARGETS


def board_disposition_rules(
    monday_board_id: str,
    *,
    sunday_board_id: str | None = None,
) -> BoardRules:
    """Regras de disposição do board. Audiências tem regras aprovadas; demais → CREATE."""
    if monday_board_id == AUDIENCIAS_MONDAY_BOARD_ID:
        return audiencias_rules()
    target_id = sunday_board_id or WAVE1_TARGETS.get(monday_board_id, (None,))[0] or ""
    return BoardRules(
        monday_board_id=monday_board_id,
        sunday_board_id=target_id,
    )
