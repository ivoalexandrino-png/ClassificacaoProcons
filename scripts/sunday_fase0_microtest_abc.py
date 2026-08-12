#!/usr/bin/env python3
"""Sunday API F0.14 microtests A/B/C — relation, business status, Área (sandbox 80/81).

Escopo estrito (NÃO repete Fase 0 inteira):
- Teste A: coluna board_relation com source_board_id=81 (label preferida
  "TESTE - RELAÇÃO BOARD 81"; fallback: qualquer board_relation apontando para 81).
- Teste B: coluna "TESTE - STATUS NEGÓCIO" — gravar/ler/alterar status customizado.
- Teste C: coluna estrutural "Área" — somente leitura (key, tipo, default, ignorável).

Escrita autorizada somente nos boards 80 e 81. Não altera colunas, grupos ou boards.

Uso:
    SUNDAY_API_URL=https://... SUNDAY_API_TOKEN=... \\
        python scripts/sunday_fase0_microtest_abc.py \\
        --out docs/sunday-fase0-microtest-abc-report.json
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

BOARD_MAIN = "80"
BOARD_RELATION = "81"
WORKSPACE_ID = "22"

RELATION_LABEL_PREFERRED = "TESTE - RELAÇÃO BOARD 81"
STATUS_LABEL = "TESTE - STATUS NEGÓCIO"
AREA_LABEL = "Área"

ITEM_MAIN_PREFIX = "TESTE MICROTEST ABC - PODE EXCLUIR"
ITEM_TARGET_PREFIX = "TESTE TARGET RELATION ABC - PODE EXCLUIR"

SENSITIVE_HEADERS = {"authorization", "x-sunday-token", "x-api-key"}
PRIVATE_FIELDS = {
    "email",
    "owner_user_id",
    "creator_user_id",
    "assignee_user_ids",
    "members",
    "team_ids",
    "avatar_url",
}


DEFAULT_API_BASE = "https://sunday-api-757613635701.us-central1.run.app"


def _token() -> str:
    token = os.environ.get("SUNDAY_API_TOKEN", "").strip()
    # Secrets occasionally arrive swapped: URL field holds sun_pat_* token.
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


def _norm_label(label: str) -> str:
    return " ".join(label.lower().split())


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


def api(method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
    url = f"{_base()}{path}"
    headers = {"X-Sunday-Token": _token()}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8")
    try:
        payload = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        payload = raw[:500]
    return status, _sanitize(payload)


def find_column(columns: list[dict], label: str) -> dict | None:
    target = _norm_label(label)
    for col in columns:
        if _norm_label(col.get("label", "")) == target:
            return col
    return None


def find_relation_column_board81(columns: list[dict]) -> dict | None:
    preferred = find_column(columns, RELATION_LABEL_PREFERRED)
    if preferred is not None:
        return preferred
    for col in columns:
        if col.get("type") != "board_relation":
            continue
        source = str((col.get("settings") or {}).get("source_board_id", ""))
        if source == BOARD_RELATION:
            return col
    return None


def extract_linked_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        ids: list[str] = []
        for x in value:
            ids.extend(extract_linked_ids(x))
        return ids
    if isinstance(value, dict):
        if "item_id" in value:
            return [str(value["item_id"])]
        for key in ("links", "item_ids", "linked_item_ids", "ids"):
            if key in value and isinstance(value[key], list):
                ids = []
                for x in value[key]:
                    ids.extend(extract_linked_ids(x))
                return ids
    return []


def read_value(item_id: str, column_id: str) -> Any:
    status, values = api("GET", f"/boards/items/{item_id}/values")
    if status != 200 or not isinstance(values, list):
        return None
    for row in values:
        if str(row.get("column_id")) == str(column_id):
            return row.get("value")
    return None


def write_value(item_id: str, column_id: str, value: Any) -> tuple[int, Any]:
    return api("PATCH", f"/boards/items/{item_id}/values/{column_id}", {"value": value})


def item_on_board(board_id: str, item_id: str) -> bool:
    status, items = api("GET", f"/boards/{board_id}/items")
    if status != 200 or not isinstance(items, list):
        return False
    return any(str(it.get("id")) == str(item_id) for it in items)


def get_item_from_board(board_id: str, item_id: str) -> dict | None:
    status, items = api("GET", f"/boards/{board_id}/items")
    if status != 200 or not isinstance(items, list):
        return None
    for it in items:
        if str(it.get("id")) == str(item_id):
            return it
    return None


def find_or_create_target_item() -> str | None:
    status, items = api("GET", f"/boards/{BOARD_RELATION}/items")
    if status == 200 and isinstance(items, list):
        for it in items:
            name = str(it.get("name", ""))
            if ITEM_TARGET_PREFIX in name:
                return str(it["id"])
    stamp = datetime.now(UTC).strftime("%H%M%S")
    create_status, body = api(
        "POST",
        f"/boards/{BOARD_RELATION}/items",
        {"name": f"{ITEM_TARGET_PREFIX} {stamp}"},
    )
    if create_status in (200, 201) and isinstance(body, dict):
        return str(body["id"])
    return None


def create_second_target_item() -> str | None:
    stamp = datetime.now(UTC).strftime("%H%M%S")
    create_status, body = api(
        "POST",
        f"/boards/{BOARD_RELATION}/items",
        {"name": f"{ITEM_TARGET_PREFIX} ALT {stamp}"},
    )
    if create_status in (200, 201) and isinstance(body, dict):
        return str(body["id"])
    return None


def relation_payload_candidates(target_id: str) -> list[tuple[str, Any]]:
    return [
        ("links_object", {"links": [{"item_id": target_id}]}),
        ("item_id_string", target_id),
        ("item_ids_array", [target_id]),
        ("item_ids_object", {"item_ids": [target_id]}),
    ]


def pick_working_relation_payload(
    item_id: str, column_id: str, target_id: str
) -> tuple[str | None, Any, list[dict]]:
    attempts: list[dict] = []
    for name, payload in relation_payload_candidates(target_id):
        status, body = write_value(item_id, column_id, payload)
        read_back = read_value(item_id, column_id)
        ok = status == 200 and target_id in extract_linked_ids(read_back)
        attempts.append(
            {
                "format": name,
                "write_http": status,
                "write_body": body,
                "read_back": read_back,
                "target_in_read_back": ok,
            }
        )
        if ok:
            return name, payload, attempts
    return None, None, attempts


def clear_relation(item_id: str, column_id: str) -> tuple[str | None, list[dict]]:
    clears: list[dict] = []
    for name, payload in (
        ("null", None),
        ("empty_links", {"links": []}),
        ("empty_string", ""),
    ):
        status, body = write_value(item_id, column_id, payload)
        read_back = read_value(item_id, column_id)
        cleared = read_back is None or extract_linked_ids(read_back) == []
        clears.append(
            {
                "format": name,
                "write_http": status,
                "read_back": read_back,
                "cleared": cleared,
            }
        )
        if cleared:
            return name, clears
    return None, clears


def test_a_relation(columns: list[dict], main_item_id: str) -> dict[str, Any]:
    result: dict[str, Any] = {"test": "A", "label": "RELAÇÃO CORRETA (source_board_id=81)"}
    rel_col = find_relation_column_board81(columns)
    if rel_col is None:
        result["verdict"] = "BLOCKED"
        result["error"] = (
            f"Coluna não encontrada ({RELATION_LABEL_PREFERRED} ou source_board_id=81)"
        )
        return result

    settings = rel_col.get("settings") or {}
    source_board = str(settings.get("source_board_id", ""))
    result["column"] = {
        "id": rel_col["id"],
        "key": rel_col.get("key"),
        "label": rel_col.get("label"),
        "type": rel_col.get("type"),
        "settings": settings,
    }
    result["source_board_id_confirmed"] = source_board == BOARD_RELATION
    if source_board != BOARD_RELATION:
        result["verdict"] = "BLOCKED"
        result["error"] = f"source_board_id={source_board!r}, esperado {BOARD_RELATION}"
        return result

    target_a = find_or_create_target_item()
    target_b = create_second_target_item()
    if not target_a or not target_b:
        result["verdict"] = "BLOCKED"
        result["error"] = "Não foi possível criar itens alvo no board 81"
        return result

    result["target_items"] = {"primary": target_a, "secondary": target_b}
    col_id = str(rel_col["id"])

    fmt, payload, discovery = pick_working_relation_payload(main_item_id, col_id, target_a)
    result["payload_discovery"] = discovery
    if fmt is None:
        result["verdict"] = "B — FUNCIONA COM FALLBACK LOCAL"
        result["classification_reason"] = "Nenhum payload gravou e releu target item_id"
        return result

    read_1 = read_value(main_item_id, col_id)
    target_on_81 = item_on_board(BOARD_RELATION, target_a)
    result["steps"] = {
        "1_write": {"format": fmt, "payload": payload, "read_back": read_1},
        "2_target_exists_on_board_81": target_on_81,
        "3_read_target_item_id": extract_linked_ids(read_1),
    }

    # update relation
    upd_payload = relation_payload_candidates(target_b)[0][1]
    upd_status, upd_body = write_value(main_item_id, col_id, upd_payload)
    read_2 = read_value(main_item_id, col_id)
    update_ok = upd_status == 200 and target_b in extract_linked_ids(read_2)
    result["steps"]["4_update"] = {
        "write_http": upd_status,
        "read_back": read_2,
        "match_secondary": update_ok,
    }

    # remove
    clear_fmt, clear_attempts = clear_relation(main_item_id, col_id)
    read_3 = read_value(main_item_id, col_id)
    removed = extract_linked_ids(read_3) == []
    result["steps"]["5_remove"] = {
        "clear_format": clear_fmt,
        "attempts": clear_attempts,
        "read_back": read_3,
        "removed": removed,
    }

    # recreate
    rec_status, rec_body = write_value(main_item_id, col_id, payload)
    read_4 = read_value(main_item_id, col_id)
    recreated = rec_status == 200 and target_a in extract_linked_ids(read_4)
    result["steps"]["6_recreate"] = {
        "write_http": rec_status,
        "read_back": read_4,
        "match_primary": recreated,
    }

    # semantic checks
    native_signals = {
        "write_read_roundtrip": target_a in extract_linked_ids(read_1),
        "structured_links_format": isinstance(read_1, dict) and "links" in read_1,
        "target_item_on_source_board": target_on_81,
        "update_works": update_ok,
        "remove_works": removed,
        "recreate_works": recreated,
    }
    result["native_signals"] = native_signals

    # links endpoint probe (read-only)
    links_status, links_body = api("GET", f"/boards/{BOARD_MAIN}/links")
    item_links_status, item_links_body = api("GET", f"/boards/items/{main_item_id}/links")
    result["links_endpoint"] = {
        "board_links_http": links_status,
        "item_links_http": item_links_status,
        "board_links_sample": links_body if links_status == 200 else None,
        "item_links_sample": item_links_body if item_links_status == 200 else None,
    }

    all_core = all(
        [
            native_signals["write_read_roundtrip"],
            native_signals["target_item_on_source_board"],
            native_signals["update_works"],
            native_signals["remove_works"],
            native_signals["recreate_works"],
        ]
    )
    if all_core:
        result["verdict"] = "A — FUNCIONA NATIVAMENTE"
        result["recommended_payload"] = {"format": fmt, "value": payload}
        result["classification_reason"] = (
            "Gravação, releitura, update, remoção e recriação funcionam com "
            f"source_board_id={BOARD_RELATION}; target item_id confirmado no board 81."
        )
    else:
        result["verdict"] = "B — FUNCIONA COM FALLBACK LOCAL"
        result["classification_reason"] = (
            "API persiste valor mas ciclo completo ou integridade semântica falhou: "
            f"{native_signals}"
        )
    return result


def test_b_status_negocio(columns: list[dict], main_item_id: str) -> dict[str, Any]:
    result: dict[str, Any] = {"test": "B", "label": STATUS_LABEL}
    col = find_column(columns, STATUS_LABEL)
    if col is None:
        result["verdict"] = "BLOCKED"
        result["error"] = "Coluna não encontrada"
        return result

    col_id = str(col["id"])
    col_key = col.get("key")
    col_type = col.get("type")
    settings = col.get("settings") or {}
    result["column"] = {
        "id": col_id,
        "key": col_key,
        "type": col_type,
        "settings": settings,
        "is_system": col.get("is_system"),
    }

    options: list[dict] = []
    if col_type == "status":
        options = list(settings.get("options") or [])
    elif col_type == "dropdown":
        options = list(settings.get("options") or [])
    result["options_discovered"] = options

    if not options:
        result["verdict"] = "BLOCKED"
        result["error"] = "Nenhuma opção configurada na coluna"
        return result

    first_key = str(options[0].get("key") or options[0].get("id") or options[0].get("label"))
    second_key = first_key
    if len(options) > 1:
        second_key = str(options[1].get("key") or options[1].get("id") or options[1].get("label"))

    attempts: list[dict] = []

    def try_write(label: str, value: Any) -> tuple[int, Any, Any]:
        if col_type == "status" and col.get("is_system"):
            st, body = api("PATCH", f"/boards/items/{main_item_id}/status", {"status": value})
        else:
            st, body = write_value(main_item_id, col_id, value)
        rb = read_value(main_item_id, col_id)
        attempts.append({"step": label, "sent": value, "write_http": st, "read_back": rb})
        return st, body, rb

    st1, _, rb1 = try_write("set_first", first_key)
    st2, _, rb2 = try_write("set_second", second_key)

    match1 = _status_matches(rb1, first_key)
    match2 = _status_matches(rb2, second_key)
    result["attempts"] = attempts
    result["match_first"] = match1
    result["match_second"] = match2

    if match1 and match2:
        result["verdict"] = "OK — status de negócio atualizável pela API"
        result["recommended_architecture"] = (
            "Usar coluna status customizada (não system status) controlada pela integração."
        )
        result["recommended_payload"] = {
            "route": f"PATCH /boards/items/{{id}}/values/{col_id}",
            "body": {"value": "<option_key>"},
        }
    else:
        result["verdict"] = "FALLBACK"
        result["recommended_architecture"] = (
            "Manter status de negócio em coluna text/dropdown ou espelhar no cache local; "
            "system status do board só para workflow visual."
        )
    return result


def _status_matches(read_back: Any, expected_key: str) -> bool:
    if read_back is None:
        return False
    if isinstance(read_back, str):
        return read_back == expected_key
    if isinstance(read_back, dict):
        for k in ("key", "status", "value"):
            if str(read_back.get(k, "")) == expected_key:
                return True
    return str(read_back) == expected_key


def test_c_area(columns: list[dict], main_item_id: str) -> dict[str, Any]:
    result: dict[str, Any] = {"test": "C", "label": AREA_LABEL, "write_performed": False}
    col = find_column(columns, AREA_LABEL)
    if col is None:
        result["verdict"] = "NOT_FOUND"
        return result

    result["column"] = {
        "id": col.get("id"),
        "key": col.get("key"),
        "type": col.get("type"),
        "label": col.get("label"),
        "is_system": col.get("is_system"),
        "settings": col.get("settings"),
    }

    item = get_item_from_board(BOARD_MAIN, main_item_id)
    area_key = col.get("key", "area")
    area_top = item.get(area_key) if item else None
    area_value = read_value(main_item_id, str(col["id"])) if col.get("id") else None

    result["on_created_item"] = {
        "item_id": main_item_id,
        "top_level_field": area_top,
        "values_route": area_value,
        "present_top_level": area_key in (item or {}),
        "has_default_value": area_top is not None or area_value is not None,
    }
    result["adapter_may_ignore"] = True
    result["verdict"] = "OK — coluna estrutural ignorável pelo adapter"
    result["notes"] = (
        "Área é coluna de sistema estrutural; criação de item funciona sem informá-la. "
        "O adapter não deve tentar excluir ou modificar esta coluna."
    )
    return result


def build_matrix(tests: dict[str, Any]) -> dict[str, str]:
    rel = tests.get("A_relation", {})
    rel_verdict = rel.get("verdict", "D")
    if "A —" in rel_verdict:
        rel_class = "A — funciona nativamente"
    elif "B —" in rel_verdict:
        rel_class = "B — funciona com fallback"
    else:
        rel_class = "D — bloqueado / indeterminado"

    status = tests.get("B_status", {})
    if status.get("verdict", "").startswith("OK"):
        status_class = "A — funciona nativamente"
    elif status.get("verdict") == "FALLBACK":
        status_class = "B — funciona com fallback"
    else:
        status_class = "D — bloqueado / indeterminado"

    area_class = "C — configuração manual aceitável / ignorável"

    return {
        "board_relation_source_81": rel_class,
        "status_negocio_custom": status_class,
        "area_estrutural": area_class,
        "schema_colunas_custom": "C — configuração manual aceitável",
        "sunday_client_base": "A — GO (não bloqueado por este microteste)",
    }


def build_decision(tests: dict[str, Any], matrix: dict[str, str]) -> dict[str, Any]:
    rel = tests.get("A_relation", {})
    status = tests.get("B_status", {})
    area = tests.get("C_area", {})

    return {
        "f0_14_updated": True,
        "sunday_client_go": True,
        "1_board_relation_source_81": rel.get("verdict"),
        "2_recommended_relation_payload": rel.get("recommended_payload"),
        "3_relation_semantics": (
            "nativa reconhecida pelo Sunday"
            if "A —" in str(rel.get("verdict", ""))
            else (
                "persistência JSON sem garantia semântica completa — "
                "usar fallback local como reforço"
            )
        ),
        "4_status_negocio_api": status.get("verdict"),
        "5_status_strategy": status.get("recommended_architecture"),
        "6_area_behavior": area.get("on_created_item"),
        "7_area_may_ignore": area.get("adapter_may_ignore", True),
        "8_matrix_abc_corrected": matrix,
        "blockers": [
            x
            for x in [
                rel.get("error") if "BLOCKED" in str(rel.get("verdict", "")) else None,
                status.get("error") if status.get("verdict") == "BLOCKED" else None,
            ]
            if x
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sunday F0.14 microtests A/B/C")
    parser.add_argument(
        "--out",
        default="docs/sunday-fase0-microtest-abc-report.json",
        help="Caminho do relatório JSON",
    )
    args = parser.parse_args()

    report: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "sandbox": {
            "workspace": WORKSPACE_ID,
            "board_main": BOARD_MAIN,
            "board_relation": BOARD_RELATION,
        },
        "env": {
            "SUNDAY_API_URL": _base(),
            "token_present": bool(os.environ.get("SUNDAY_API_TOKEN")),
        },
    }

    me_status, me_body = api("GET", "/auth/me")
    report["auth_me"] = {"http": me_status}
    if me_status != 200:
        report["decision"] = {"verdict": "NO-GO", "reason": f"auth/me HTTP {me_status}"}
        _write_report(args.out, report)
        return 1

    col_status, columns = api("GET", f"/boards/{BOARD_MAIN}/columns")
    if col_status != 200 or not isinstance(columns, list):
        report["decision"] = {"verdict": "NO-GO", "reason": f"columns HTTP {col_status}"}
        _write_report(args.out, report)
        return 1

    report["columns_snapshot"] = [
        {
            "id": c.get("id"),
            "key": c.get("key"),
            "label": c.get("label"),
            "type": c.get("type"),
            "settings": c.get("settings"),
            "is_system": c.get("is_system"),
        }
        for c in columns
        if any(
            token in _norm_label(c.get("label", ""))
            for token in ("rela", "status neg", "área", "area")
        )
        or c.get("type") == "board_relation"
    ]

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    create_status, create_body = api(
        "POST",
        f"/boards/{BOARD_MAIN}/items",
        {"name": f"{ITEM_MAIN_PREFIX} {stamp}"},
    )
    if create_status not in (200, 201) or not isinstance(create_body, dict):
        report["decision"] = {"verdict": "NO-GO", "reason": "falha ao criar item board 80"}
        _write_report(args.out, report)
        return 1

    main_item_id = str(create_body["id"])
    report["main_item_id"] = main_item_id

    tests = {
        "A_relation": test_a_relation(columns, main_item_id),
        "B_status": test_b_status_negocio(columns, main_item_id),
        "C_area": test_c_area(columns, main_item_id),
    }
    report["tests"] = tests
    report["matrix"] = build_matrix(tests)
    report["decision"] = build_decision(tests, report["matrix"])

    _write_report(args.out, report)
    print(json.dumps(report["decision"], indent=2, ensure_ascii=False))
    return 0


def _write_report(path: str, report: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"Relatório: {path}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
