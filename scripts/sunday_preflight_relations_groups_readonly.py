#!/usr/bin/env python3
"""Preflight (SOMENTE LEITURA) — valida board_relation no Sunday e levanta grupos no Monday.

Duas validações, ambas read-only:

1. Sunday (REST, GET): confere as colunas board_relation esperadas nos boards
   83 (Prazos), 72 (Audiências, duas ocorrências) e 77 (Controle), reportando
   board / column_id / key / type / source_board_id / OK|ERRO.

2. Monday (GraphQL, apenas query): levanta os grupos dos 8 boards da Onda 1 com,
   por grupo, total de itens ativos e a divisão aberto/concluído (por coluna de
   status quando existe; senão por heurística de nome de grupo).

Nada é criado/alterado/apagado em nenhum sistema. Nenhum token é impresso.

Uso:
    SUNDAY_API_URL=... SUNDAY_API_TOKEN=... MONDAY_API_TOKEN=... \
        python scripts/sunday_preflight_relations_groups_readonly.py \
        --out docs/sunday-preflight-relations-groups-report.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

DEFAULT_API_BASE = "https://sunday-api-757613635701.us-central1.run.app"

# ---------------------------------------------------------------------------
# Sunday (REST) — validação das relações board_relation
# ---------------------------------------------------------------------------

# (board_sunday, source_board_id esperado, "quantas ocorrências dessa relação"?)
SUNDAY_RELATION_EXPECTATIONS = [
    {"board": "83", "board_name": "Legal - Prazos", "source_board_id": "84", "min_occurrences": 1},
    {
        "board": "72",
        "board_name": "Legal - Audiências",
        "source_board_id": "84",
        "min_occurrences": 2,
    },
    {
        "board": "77",
        "board_name": "Legal - Controle de Assinaturas",
        "source_board_id": "87",
        "min_occurrences": 1,
    },
]

SUNDAY_BOARDS = ["72", "77", "82", "83", "84", "85", "86", "87"]


def _sunday_token() -> str:
    token = os.environ.get("SUNDAY_API_TOKEN", "").strip()
    if not token or token.startswith("curl "):
        url_field = os.environ.get("SUNDAY_API_URL", "").strip()
        if url_field.startswith("sun_pat_"):
            token = url_field
    if not token:
        print("ERRO: SUNDAY_API_TOKEN ausente.", file=sys.stderr)
        sys.exit(2)
    return token


def _sunday_base() -> str:
    base = os.environ.get("SUNDAY_API_URL", "").strip().rstrip("/")
    if not base.startswith("http"):
        base = os.environ.get("SUNDAY_API_BASE_URL", DEFAULT_API_BASE).strip().rstrip("/")
    return base or DEFAULT_API_BASE


def sunday_get(path: str) -> tuple[int, Any]:
    url = f"{_sunday_base()}{path}"
    req = urllib.request.Request(url, headers={"X-Sunday-Token": _sunday_token()}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8")
    except urllib.error.URLError as exc:
        return 0, {"error": str(exc)}
    try:
        return status, (json.loads(raw) if raw else None)
    except json.JSONDecodeError:
        return status, raw[:500]


def _col_source_board(col: dict) -> str:
    settings = col.get("settings") or {}
    for key in ("source_board_id", "board_id", "target_board_id"):
        if settings.get(key) is not None:
            return str(settings.get(key))
    board_ids = settings.get("board_ids") or settings.get("boardIds")
    if isinstance(board_ids, list) and board_ids:
        return str(board_ids[0])
    return ""


def validate_sunday_relations() -> dict[str, Any]:
    out: dict[str, Any] = {"per_board_columns": {}, "checks": []}
    columns_by_board: dict[str, list[dict]] = {}
    for bid in SUNDAY_BOARDS:
        st, cols = sunday_get(f"/boards/{bid}/columns")
        columns_by_board[bid] = cols if isinstance(cols, list) else []
        out["per_board_columns"][bid] = {"http": st, "count": len(columns_by_board[bid])}

    for exp in SUNDAY_RELATION_EXPECTATIONS:
        bid = exp["board"]
        cols = columns_by_board.get(bid, [])
        relations = [c for c in cols if c.get("type") == "board_relation"]
        matching = [c for c in relations if _col_source_board(c) == exp["source_board_id"]]
        for idx in range(exp["min_occurrences"]):
            if idx < len(matching):
                col = matching[idx]
                out["checks"].append(
                    {
                        "board": f"{bid} — {exp['board_name']}",
                        "column_id": col.get("id"),
                        "key": col.get("key"),
                        "label": col.get("label"),
                        "type": col.get("type"),
                        "source_board_id": _col_source_board(col),
                        "verdict": "OK",
                    }
                )
            else:
                # ocorrência ausente
                other = [
                    {
                        "column_id": c.get("id"),
                        "key": c.get("key"),
                        "label": c.get("label"),
                        "type": c.get("type"),
                        "source_board_id": _col_source_board(c),
                    }
                    for c in relations
                ]
                out["checks"].append(
                    {
                        "board": f"{bid} — {exp['board_name']}",
                        "column_id": None,
                        "key": None,
                        "label": None,
                        "type": None,
                        "source_board_id": None,
                        "verdict": "ERRO",
                        "reason": (
                            f"ocorrência {idx + 1} de board_relation com "
                            f"source_board_id={exp['source_board_id']} não encontrada"
                        ),
                        "board_relation_columns_present": other,
                    }
                )
    return out


def sunday_groups_snapshot() -> dict[str, Any]:
    snap: dict[str, Any] = {}
    for bid in SUNDAY_BOARDS:
        st, groups = sunday_get(f"/boards/{bid}/groups")
        rows = []
        if isinstance(groups, list):
            for g in groups:
                rows.append({"id": g.get("id"), "title": g.get("title") or g.get("name")})
        snap[bid] = {"http": st, "groups": rows}
    return snap


# ---------------------------------------------------------------------------
# Monday (GraphQL) — levantamento de grupos
# ---------------------------------------------------------------------------

MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_API_VERSION = "2024-10"

MONDAY_BOARDS = {
    "4944254220": "Procons",
    "3961072966": "Prazos",
    "4443295406": "Audiências",
    "5343921475": "Processos Judiciais",
    "4443297481": "Processos Trabalhista",
    "5563754463": "KPI Processos Consumidores",
    "5301515799": "Controle Assinaturas",
    "5385471914": "Contratos",
}

# Coluna de status de negócio por board (título -> rótulos que significam "concluído").
STATUS_CONFIG = {
    "4944254220": ("Status", {"baixado", "respondido"}),
    "3961072966": ("Status", {"feito", "cancelada", "nao realizada", "não realizada"}),
    "4443295406": ("Status", {"feito", "cancelada", "encerrado"}),
    "5343921475": ("Status", {"encerrado"}),
    "4443297481": ("Status", {"encerrado"}),
    "5563754463": ("Situação", {"arquivado"}),
    "5385471914": ("Vigência", {"nao vigente", "não vigente"}),
    # 5301515799 (Controle) usa heurística de grupo (greenfield, não migra o legado).
}

_DONE_GROUP_TOKENS = (
    "encerrad",
    "conclu",
    "arquiv",
    "assinad",
    "finaliz",
    "baixad",
    "recusad",
    "cumprido",
    "resolvido",
    "inativ",
    " done",
)


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _is_done_group(title: str) -> bool:
    n = _norm(title)
    return any(tok.strip() in n for tok in _DONE_GROUP_TOKENS)


def monday_query(query: str, variables: dict) -> dict:
    token = os.environ["MONDAY_API_TOKEN"]
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        MONDAY_API_URL,
        data=body,
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
            "API-Version": MONDAY_API_VERSION,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


BOARD_META_QUERY = """
query($ids: [ID!]) {
  boards(ids: $ids) {
    id name items_count
    groups { id title }
    columns { id title type }
  }
}
"""

GROUP_ITEMS_QUERY = """
query($board: [ID!], $group: [String!], $cols: [String!]) {
  boards(ids: $board) {
    groups(ids: $group) {
      id title
      items_page(limit: 200) {
        cursor
        items { id state column_values(ids: $cols) { id text } }
      }
    }
  }
}
"""

NEXT_PAGE_QUERY = """
query($cursor: String!, $cols: [String!]) {
  next_items_page(cursor: $cursor, limit: 200) {
    cursor
    items { id state column_values(ids: $cols) { id text } }
  }
}
"""


def _resolve_status_col(board_id: str, columns: list[dict]) -> str | None:
    cfg = STATUS_CONFIG.get(board_id)
    if not cfg:
        return None
    title_target = _norm(cfg[0])
    for col in columns:
        if _norm(col.get("title", "")) == title_target and col.get("type") in {
            "status",
            "color",
            "dropdown",
        }:
            return str(col.get("id"))
    return None


def _classify_item(
    item: dict, status_col: str | None, done_labels: set[str], group_is_done: bool
) -> str:
    if item.get("state") != "active":
        return "inactive"
    if status_col:
        for cv in item.get("column_values") or []:
            if str(cv.get("id")) == status_col:
                txt = _norm(cv.get("text", ""))
                if txt and any(lbl == txt for lbl in done_labels):
                    return "done"
                return "open"
        # sem valor de status -> considerar aberto
        return "open"
    return "done" if group_is_done else "open"


def survey_monday_groups() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for board_id, short in MONDAY_BOARDS.items():
        meta = monday_query(BOARD_META_QUERY, {"ids": [board_id]})
        boards = meta.get("data", {}).get("boards", [])
        if not boards:
            result[board_id] = {"name": short, "error": meta}
            continue
        board = boards[0]
        columns = board.get("columns", [])
        status_col = _resolve_status_col(board_id, columns)
        done_labels = STATUS_CONFIG.get(board_id, ("", set()))[1]
        cols_arg = [status_col] if status_col else []

        groups_out = []
        board_total_active = 0
        for g in board.get("groups", []):
            gid = g["id"]
            gtitle = g["title"]
            group_done = _is_done_group(gtitle)
            counts = {"total_active": 0, "open": 0, "done": 0, "inactive": 0}
            variables = {"board": [board_id], "group": [gid], "cols": cols_arg}
            page = monday_query(GROUP_ITEMS_QUERY, variables)
            gnode = page.get("data", {}).get("boards", [{}])[0].get("groups", [])
            if not gnode:
                groups_out.append(
                    {"group_id": gid, "title": gtitle, "counts": counts, "error": page}
                )
                continue
            ip = gnode[0].get("items_page", {})
            while True:
                for it in ip.get("items", []):
                    cls = _classify_item(it, status_col, done_labels, group_done)
                    if cls == "inactive":
                        counts["inactive"] += 1
                    else:
                        counts["total_active"] += 1
                        counts[cls] += 1
                cursor = ip.get("cursor")
                if not cursor:
                    break
                nxt = monday_query(NEXT_PAGE_QUERY, {"cursor": cursor, "cols": cols_arg})
                ip = nxt.get("data", {}).get("next_items_page", {}) or {}
                if not ip.get("items"):
                    break
            board_total_active += counts["total_active"]
            groups_out.append(
                {
                    "group_id": gid,
                    "title": gtitle,
                    "group_name_is_done_bucket": group_done,
                    "counts": counts,
                }
            )
        result[board_id] = {
            "name": board.get("name"),
            "short": short,
            "items_count_reported": board.get("items_count"),
            "status_column_used": status_col,
            "status_column_title": STATUS_CONFIG.get(board_id, (None, None))[0],
            "done_labels": sorted(done_labels),
            "board_total_active_counted": board_total_active,
            "groups": groups_out,
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight read-only relations + groups")
    parser.add_argument("--out", default="docs/sunday-preflight-relations-groups-report.json")
    args = parser.parse_args()

    report: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "read_only": True,
        "sunday_base": _sunday_base(),
    }

    print("== Validando relações no Sunday ==", file=sys.stderr)
    report["sunday_relations"] = validate_sunday_relations()
    report["sunday_groups"] = sunday_groups_snapshot()

    print("== Levantando grupos no Monday ==", file=sys.stderr)
    report["monday_groups"] = survey_monday_groups()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"Relatório salvo em: {args.out}", file=sys.stderr)

    # Resumo legível
    print("\n--- RELAÇÕES (Sunday) ---")
    for chk in report["sunday_relations"]["checks"]:
        print(
            f"{chk['board']} | col={chk['column_id']} key={chk['key']} "
            f"type={chk['type']} source_board_id={chk['source_board_id']} -> {chk['verdict']}"
        )
    print("\n--- GRUPOS (Monday) ---")
    for bid, info in report["monday_groups"].items():
        if "groups" not in info:
            print(f"{bid} {info.get('name')}: ERRO {info.get('error')}")
            continue
        print(f"\n[{bid}] {info['name']} (status_col={info['status_column_title']})")
        for g in info["groups"]:
            c = g["counts"]
            print(
                f"  - {g['title']!r} (id={g['group_id']}): "
                f"total_ativos={c['total_active']} abertos={c['open']} "
                f"concluídos={c['done']} (done_bucket={g.get('group_name_is_done_bucket')})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
