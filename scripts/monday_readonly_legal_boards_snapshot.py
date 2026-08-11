#!/usr/bin/env python3
"""Somente leitura (GraphQL query, nunca mutation) — snapshot dos 8 boards legais no Monday
(Onda 1 da migração Sunday). Não cria, altera nem apaga nada no Monday.

Usado na Fase 2.5 (preflight) para servir de base real ao checklist manual do Sunday,
já que o repositório não tem uma Fase 2 (F2.x) documentada com o de-para de colunas/status.

Uso:
    MONDAY_API_TOKEN=... python scripts/monday_readonly_legal_boards_snapshot.py \
        --out docs/sunday-fase2-5-monday-snapshot.json
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request

MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_API_VERSION = "2024-10"

BOARD_IDS = {
    "prazos": "3961072966",
    "audiencias": "4443295406",
    "processos_judiciais": "5343921475",
    "processos_trabalhista": "4443297481",
    "kpi_processos_consumidores": "5563754463",
    "procons": "4944254220",
    "contratos": "5385471914",
    "controle_assinaturas": "5301515799",
}

QUERY = """
query($ids: [ID!]) {
  boards (ids: $ids) {
    id
    name
    items_count
    groups { id title }
    columns { id title type settings_str }
  }
}
"""


def _run(query: str, variables: dict) -> dict:
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
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Snapshot somente leitura dos boards legais Monday"
    )
    parser.add_argument("--out", default="docs/sunday-fase2-5-monday-snapshot.json")
    args = parser.parse_args()

    out: dict = {}
    for key, board_id in BOARD_IDS.items():
        res = _run(QUERY, {"ids": [board_id]})
        boards = res.get("data", {}).get("boards", [])
        out[key] = boards[0] if boards else {"error": res}

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print(f"Snapshot salvo em: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
