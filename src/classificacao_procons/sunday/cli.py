"""CLI de discovery/leitura do Sunday (``sunday``).

Espelha a sondagem manual da migração: inspeciona workspaces, boards, colunas,
grupos e itens da API REST do Sunday. Somente leitura.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from classificacao_procons.sunday.client import SundayClient, SundayClientError


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _run_me(_: argparse.Namespace) -> int:
    client = SundayClient.from_env()
    me = client.get_me()
    _print({"id": me.get("id"), "email": me.get("email"), "job_title": me.get("job_title")})
    return 0


def _run_workspaces(_: argparse.Namespace) -> int:
    client = SundayClient.from_env()
    _print([asdict(ws) for ws in client.list_workspaces()])
    return 0


def _run_boards(args: argparse.Namespace) -> int:
    client = SundayClient.from_env()
    boards = client.list_boards(workspace_id=args.workspace_id)
    _print([asdict(board) for board in boards])
    return 0


def _run_board(args: argparse.Namespace) -> int:
    client = SundayClient.from_env()
    board = client.get_board(args.board_id)
    columns = client.list_columns(args.board_id)
    groups = client.list_groups(args.board_id)
    items = client.list_items(args.board_id)
    _print(
        {
            "board": asdict(board),
            "columns": [asdict(column) for column in columns],
            "groups": [asdict(group) for group in groups],
            "item_count": len(items),
            "items": [{"id": item.id, "name": item.name} for item in items],
        },
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sunday",
        description="Discovery/leitura da API REST do Sunday (sunday.b4a.ai).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("me", help="Perfil autenticado (GET /auth/me)")
    sub.add_parser("workspaces", help="Lista workspaces")

    boards = sub.add_parser("boards", help="Lista boards (opcionalmente de um workspace)")
    boards.add_argument("--workspace-id", default=None, help="Filtra por workspace")

    board = sub.add_parser("board", help="Detalha um board (colunas, grupos, itens)")
    board.add_argument("board_id", help="ID do board")

    args = parser.parse_args(argv)

    handlers = {
        "me": _run_me,
        "workspaces": _run_workspaces,
        "boards": _run_boards,
        "board": _run_board,
    }
    try:
        return handlers[args.command](args)
    except SundayClientError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
