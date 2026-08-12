#!/usr/bin/env python3
"""Fase 2.5 — validação SOMENTE LEITURA dos 8 boards da Onda 1 (workspace 22).

Escopo estrito: nenhuma escrita. Apenas GET em /auth/me, /workspaces/22,
/boards, /boards/{id}, /boards/{id}/columns, /boards/{id}/groups,
/boards/{id}/items (contagem), /boards/{id}/status_set (se existir),
/users (diretório, para matching agregado de usuários).

Não grava nada em nenhum board. Não expõe token. Sanitiza campos sensíveis
(e-mail, ids de usuário) do relatório.

Uso:
    SUNDAY_API_URL=... SUNDAY_API_TOKEN=... \
        python scripts/sunday_fase2_5_readonly_validation.py \
        --out docs/sunday-fase2-5-readonly-report.json
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

WORKSPACE_ID = "22"
BOARD_IDS = ["72", "77", "82", "83", "84", "85", "86", "87"]
EXPECTED_NAMES = {
    "72": "Legal - Audiências",
    "77": "Legal - Controle de Assinaturas",
    "82": "Legal - Procons",
    "83": "Legal - Prazos",
    "84": "Legal - Processos Judiciais",
    "85": "Legal - Processos Trabalhista",
    "86": "Legal - KPI Processos Consumidores",
    "87": "Legal - Contratos",
}

PRIVATE_FIELDS = {
    "email",
    "owner_user_id",
    "creator_user_id",
    "assignee_user_ids",
    "members",
    "team_ids",
    "avatar_url",
    "phone",
    "calendar_event_organizer_email",
}

DEFAULT_API_BASE = "https://sunday-api-757613635701.us-central1.run.app"


def _token() -> str:
    token = os.environ.get("SUNDAY_API_TOKEN", "").strip()
    if not token or token.startswith("curl "):
        url_field = os.environ.get("SUNDAY_API_URL", "").strip()
        if url_field.startswith("sun_pat_"):
            token = url_field
    if not token:
        print("ERRO: SUNDAY_API_TOKEN ausente.", file=sys.stderr)
        sys.exit(2)
    return token


def _base() -> str:
    base = os.environ.get("SUNDAY_API_URL", "").strip().rstrip("/")
    if not base.startswith("http"):
        base = os.environ.get("SUNDAY_API_BASE_URL", DEFAULT_API_BASE).strip().rstrip("/")
    if not base:
        print("ERRO: SUNDAY_API_URL ausente.", file=sys.stderr)
        sys.exit(2)
    return base


def _sanitize(value: Any) -> Any:
    token = os.environ.get("SUNDAY_API_TOKEN", "")
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in PRIVATE_FIELDS:
                out[key] = "<omitido>"
            else:
                out[key] = _sanitize(item)
        return out
    if isinstance(value, list):
        return [_sanitize(x) for x in value]
    if isinstance(value, str) and token and token in value:
        return value.replace(token, "[REDACTED]")
    return value


def api(method: str, path: str) -> tuple[int, Any]:
    assert method == "GET", "Este script é somente leitura (GET)."
    url = f"{_base()}{path}"
    headers = {"X-Sunday-Token": _token()}
    req = urllib.request.Request(url, headers=headers, method=method)
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
        payload = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        payload = raw[:1000]
    return status, _sanitize(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fase 2.5 read-only validation")
    parser.add_argument("--out", default="docs/sunday-fase2-5-readonly-report.json")
    args = parser.parse_args()

    report: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "workspace": WORKSPACE_ID,
        "read_only": True,
    }

    me_status, me_body = api("GET", "/auth/me")
    report["auth_me"] = {"http": me_status, "body": me_body}

    ws_status, ws_body = api("GET", f"/workspaces/{WORKSPACE_ID}")
    report["workspace"] = {"http": ws_status, "body": ws_body}

    boards_status, boards_body = api("GET", "/boards")
    report["boards_list"] = {"http": boards_status, "body": boards_body}

    per_board: dict[str, Any] = {}
    for bid in BOARD_IDS:
        entry: dict[str, Any] = {"expected_name": EXPECTED_NAMES[bid]}
        st, body = api("GET", f"/boards/{bid}")
        entry["board"] = {"http": st, "body": body}

        st_c, cols = api("GET", f"/boards/{bid}/columns")
        entry["columns"] = {"http": st_c, "body": cols}

        st_g, groups = api("GET", f"/boards/{bid}/groups")
        entry["groups"] = {"http": st_g, "body": groups}

        st_ss, status_set = api("GET", f"/boards/{bid}/status_set")
        entry["status_set"] = {"http": st_ss, "body": status_set}

        st_i, items = api("GET", f"/boards/{bid}/items")
        item_count = len(items) if isinstance(items, list) else None
        entry["items_summary"] = {"http": st_i, "count": item_count}

        st_a, autom = api("GET", f"/boards/{bid}/automations")
        entry["automations"] = {"http": st_a, "body": autom}

        per_board[bid] = entry

    report["per_board"] = per_board

    st_u, users = api("GET", "/users")
    if isinstance(users, list):
        users_summary = [
            {
                "id": u.get("id"),
                "name": u.get("name"),
                "is_active": u.get("is_active") if "is_active" in u else u.get("enabled"),
                "access_level": u.get("access_level"),
            }
            for u in users
            if isinstance(u, dict)
        ]
    else:
        users_summary = users
    report["users_directory"] = {
        "http": st_u,
        "count": len(users) if isinstance(users, list) else None,
        "sample": users_summary,
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"Relatório salvo em: {args.out}", file=sys.stderr)
    print(json.dumps({"auth_me_http": me_status, "boards_list_http": boards_status}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
