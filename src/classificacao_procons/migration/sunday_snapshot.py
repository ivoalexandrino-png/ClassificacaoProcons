"""Snapshot do schema dos boards Sunday (destino) — leitura viva ou arquivo JSON.

Sem o secret na sessão, o dry-run usa o snapshot versionado (levantado na F0.13/
F0.15 com leitura autenticada real). Com `SUNDAY_API_TOKEN` disponível, o script
atualiza o snapshot ao vivo usando somente métodos de LEITURA do SundayClient.
"""

from __future__ import annotations

import json
from pathlib import Path

from classificacao_procons.migration.models import (
    SundayBoardSnapshot,
    SundayColumnSnapshot,
)


def snapshot_from_payload(payload: dict) -> dict[str, SundayBoardSnapshot]:
    snapshots: dict[str, SundayBoardSnapshot] = {}
    for board in payload.get("boards", []):
        columns = tuple(
            SundayColumnSnapshot(
                id=str(column["id"]),
                key=column.get("key"),
                label=str(column.get("label", "")),
                type=str(column.get("type", "")),
                is_system=bool(column.get("is_system")),
                settings=column.get("settings") or {},
            )
            for column in board.get("columns", [])
        )
        snapshot = SundayBoardSnapshot(
            board_id=str(board["board_id"]),
            name=str(board.get("name", "")),
            columns=columns,
            status_keys=tuple(board.get("status_keys") or ()),
            groups=board.get("groups") or {},
        )
        snapshots[snapshot.board_id] = snapshot
    return snapshots


def load_snapshot_file(path: str | Path) -> dict[str, SundayBoardSnapshot]:
    return snapshot_from_payload(json.loads(Path(path).read_text(encoding="utf-8")))


def snapshot_from_live_client(client, board_ids: list[str]) -> dict[str, SundayBoardSnapshot]:
    """Constrói o snapshot ao vivo — SOMENTE leituras (get_board/list_columns/groups)."""
    snapshots: dict[str, SundayBoardSnapshot] = {}
    for board_id in board_ids:
        board = client.get_board(board_id)
        columns = tuple(
            SundayColumnSnapshot(
                id=column.id,
                key=column.key,
                label=column.label,
                type=column.type,
                is_system=column.is_system,
                settings=column.settings,
            )
            for column in client.list_columns(board_id)
        )
        groups = {group.id: group.name for group in client.list_groups(board_id)}
        snapshots[board_id] = SundayBoardSnapshot(
            board_id=board.id,
            name=board.name,
            columns=columns,
            status_keys=board.status_keys(),
            groups=groups,
        )
    return snapshots
