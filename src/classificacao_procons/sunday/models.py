"""Modelos do domínio Sunday (API REST)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SundayStatusLabel:
    """Label de uma coluna status (``status_set`` do board)."""

    key: str
    label: str
    color: str | None = None
    terminal: bool = False


@dataclass(frozen=True)
class SundayWorkspace:
    id: str
    name: str
    slug: str | None = None
    business_unit: str | None = None
    board_count: int | None = None
    member_count: int | None = None
    archived: bool = False


@dataclass(frozen=True)
class SundayBoard:
    id: str
    name: str
    description: str | None = None
    status: str | None = None
    template_key: str | None = None
    workspace_id: str | None = None
    status_set: tuple[SundayStatusLabel, ...] = ()


@dataclass(frozen=True)
class SundayColumn:
    id: str
    key: str
    type: str
    label: str
    board_id: str | None = None
    position: int | None = None
    is_system: bool = False
    settings: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SundayGroup:
    id: str
    name: str
    board_id: str | None = None
    color: str | None = None
    position: int | None = None


@dataclass(frozen=True)
class SundayItem:
    """Item de um board.

    Como os boards legais do Sunday ainda estão vazios (discovery 2026-08-10), o
    formato dos valores de coluna de um item preenchido ainda não foi observado.
    Guardamos o payload cru em ``raw`` para não presumir a forma antes da hora.
    """

    id: str
    name: str
    group_id: str | None = None
    raw: dict = field(default_factory=dict)
