"""Parsing dos payloads REST do Sunday para os modelos do domínio.

Funções puras (sem rede), testáveis offline com os payloads reais observados no
discovery. Todas toleram campos ausentes.
"""

from __future__ import annotations

from typing import Any

from classificacao_procons.sunday.models import (
    SundayBoard,
    SundayColumn,
    SundayGroup,
    SundayItem,
    SundayStatusLabel,
    SundayWorkspace,
)


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_status_label(payload: dict) -> SundayStatusLabel:
    return SundayStatusLabel(
        key=str(payload.get("key", "")),
        label=str(payload.get("label", "")),
        color=_as_str(payload.get("color")),
        terminal=bool(payload.get("terminal", False)),
    )


def parse_workspace(payload: dict) -> SundayWorkspace:
    return SundayWorkspace(
        id=str(payload.get("id", "")),
        name=str(payload.get("name", "")),
        slug=_as_str(payload.get("slug")),
        business_unit=_as_str(payload.get("business_unit")),
        board_count=_as_int(payload.get("board_count")),
        member_count=_as_int(payload.get("member_count")),
        archived=bool(payload.get("archived", False)),
    )


def parse_board(payload: dict) -> SundayBoard:
    status_set = tuple(
        parse_status_label(label)
        for label in payload.get("status_set", [])
        if isinstance(label, dict)
    )
    return SundayBoard(
        id=str(payload.get("id", "")),
        name=str(payload.get("name", "")),
        description=_as_str(payload.get("description")),
        status=_as_str(payload.get("status")),
        template_key=_as_str(payload.get("template_key")),
        workspace_id=_as_str(payload.get("workspace_id")),
        status_set=status_set,
    )


def parse_column(payload: dict) -> SundayColumn:
    return SundayColumn(
        id=str(payload.get("id", "")),
        key=str(payload.get("key", "")),
        type=str(payload.get("type", "")),
        label=str(payload.get("label", "")),
        board_id=_as_str(payload.get("board_id")),
        position=_as_int(payload.get("position")),
        is_system=bool(payload.get("is_system", False)),
        settings=payload.get("settings") if isinstance(payload.get("settings"), dict) else {},
    )


def parse_group(payload: dict) -> SundayGroup:
    return SundayGroup(
        id=str(payload.get("id", "")),
        name=str(payload.get("name", "")),
        board_id=_as_str(payload.get("board_id")),
        color=_as_str(payload.get("color")),
        position=_as_int(payload.get("position")),
    )


def parse_item(payload: dict) -> SundayItem:
    name = payload.get("name")
    if name is None and isinstance(payload.get("values"), dict):
        name = payload["values"].get("name")
    return SundayItem(
        id=str(payload.get("id", "")),
        name=str(name or ""),
        group_id=_as_str(payload.get("group_id")),
        raw=payload,
    )


def parse_workspaces(payload: list) -> list[SundayWorkspace]:
    return [parse_workspace(item) for item in payload if isinstance(item, dict)]


def parse_boards(payload: list) -> list[SundayBoard]:
    return [parse_board(item) for item in payload if isinstance(item, dict)]


def parse_columns(payload: list) -> list[SundayColumn]:
    return [parse_column(item) for item in payload if isinstance(item, dict)]


def parse_groups(payload: list) -> list[SundayGroup]:
    return [parse_group(item) for item in payload if isinstance(item, dict)]


def parse_items(payload: list) -> list[SundayItem]:
    return [parse_item(item) for item in payload if isinstance(item, dict)]
