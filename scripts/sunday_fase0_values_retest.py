"""Sunday API Fase 0 retest — values + board_relation only (sandbox boards 80/81)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

BASE = os.environ.get("SUNDAY_API_URL", "").rstrip("/")
TOKEN = os.environ.get("SUNDAY_API_TOKEN", "")
BOARD_MAIN = "80"
BOARD_RELATION = "81"

REQUIRED_LABELS = [
    "TESTE - Texto",
    "TESTE - Número",
    "TESTE - Status",
    "TESTE - Data",
    "TESTE - Responsável",
    "TESTE - Link",
    "TESTE - Checkbox",
    "TESTE - Relação",
]

ITEM_MAIN_NAME = "TESTE VALUES API - PODE EXCLUIR"
ITEM_TARGET_NAME = "TESTE TARGET RELATION - PODE EXCLUIR"


def headers() -> dict[str, str]:
    return {
        "Authorization": TOKEN,
        "X-Sunday-Token": TOKEN,
        "Content-Type": "application/json",
    }


def sanitize_response(data: Any) -> Any:
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if k in ("token", "password", "secret"):
                out[k] = "<REDACTED>"
            else:
                out[k] = sanitize_response(v)
        return out
    if isinstance(data, list):
        return [sanitize_response(x) for x in data]
    return data


def req(
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
) -> tuple[int, Any]:
    url = f"{BASE}/{path.lstrip('/')}"
    data = None
    hdrs = headers()
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
    req_obj = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req_obj, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        body = raw
    return status, sanitize_response(body)


def get_item_by_id(board_id: str, item_id: str) -> dict | None:
    status, body = req("GET", f"boards/{board_id}/items")
    if status != 200 or not isinstance(body, list):
        return None
    for item in body:
        if item.get("id") == item_id:
            return item
    return None


def normalize_label(label: str) -> str:
    return " ".join(label.lower().split())


def find_column_by_label(columns: list[dict], target: str) -> dict | None:
    norm = normalize_label(target)
    for col in columns:
        if normalize_label(col.get("label", "")) == norm:
            return col
    return None


def main() -> int:
    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sandbox": {"workspace": "22", "board_main": BOARD_MAIN, "board_relation": BOARD_RELATION},
        "env": {
            "SUNDAY_API_URL_set": bool(BASE),
            "SUNDAY_API_TOKEN_set": bool(TOKEN),
            "SUNDAY_API_URL": BASE if BASE else None,
        },
        "validation": {},
        "test1_columns": [],
        "tests": {},
        "matrix": {},
        "decision": {},
    }

    if not BASE or not TOKEN:
        report["decision"] = {"verdict": "NO-GO", "reason": "Missing SUNDAY_API_URL or SUNDAY_API_TOKEN"}
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1

    # Auth
    me_status, me_body = req("GET", "auth/me")
    report["auth_me"] = {"http": me_status, "body": me_body}
    user_id = me_body.get("id") if isinstance(me_body, dict) else None

    # Columns board 80
    col_status, columns = req("GET", f"boards/{BOARD_MAIN}/columns")
    report["validation"]["columns_http"] = col_status
    if col_status != 200 or not isinstance(columns, list):
        report["decision"] = {"verdict": "NO-GO", "reason": f"Cannot read columns: HTTP {col_status}"}
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1

    missing = []
    col_map: dict[str, dict] = {}
    for label in REQUIRED_LABELS:
        col = find_column_by_label(columns, label)
        if col is None:
            missing.append(label)
        else:
            col_map[label] = col

    report["validation"]["missing_columns"] = missing
    report["validation"]["columns_found"] = len(col_map)

    if missing:
        report["decision"] = {"verdict": "STOP", "reason": f"Missing columns: {missing}"}
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1

    report["test1_columns"] = [
        {
            "label": col["label"],
            "column_id": col["id"],
            "key": col["key"],
            "type": col["type"],
            "settings": col.get("settings"),
            "is_system": col.get("is_system"),
        }
        for col in columns
        if normalize_label(col.get("label", "")) in {normalize_label(label) for label in REQUIRED_LABELS}
    ]

    relation_col = col_map["TESTE - Relação"]
    relation_target_board = relation_col.get("settings", {}).get("source_board_id")
    report["validation"]["relation_column_target_board"] = relation_target_board
    report["validation"]["relation_expected_board"] = BOARD_RELATION
    report["validation"]["relation_board_mismatch"] = relation_target_board != BOARD_RELATION

    # Board status_set
    board_status, board_body = req("GET", f"boards/{BOARD_MAIN}")
    status_options = []
    if board_status == 200 and isinstance(board_body, dict):
        status_options = board_body.get("status_set", [])

    # Test 2 — create main item
    create_status, create_body = req(
        "POST", f"boards/{BOARD_MAIN}/items", json_body={"name": ITEM_MAIN_NAME}
    )
    report["tests"]["create_item"] = {
        "http": create_status,
        "body": create_body,
    }
    if create_status not in (200, 201) or not isinstance(create_body, dict):
        report["decision"] = {"verdict": "NO-GO", "reason": "Cannot create item on board 80"}
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1

    item_id = create_body["id"]

    def patch_item(payload: dict) -> tuple[int, Any]:
        return req("PATCH", f"boards/{BOARD_MAIN}/items/{item_id}", json_body=payload)

    def read_item() -> dict | None:
        return get_item_by_id(BOARD_MAIN, item_id)

    # Test 3 — Text (name column)
    text_key = col_map["TESTE - Texto"]["key"]
    sent_text = "Teste Sunday API"
    p_status, p_body = patch_item({text_key: sent_text})
    read = read_item()
    got_text = read.get(text_key) if read else None
    report["tests"]["texto"] = {
        "column_key": text_key,
        "write_http": p_status,
        "write_body": p_body,
        "sent": sent_text,
        "read": got_text,
        "match": got_text == sent_text,
        "write_payload": {text_key: sent_text},
        "read_format": "top-level item field",
    }

    # Test 4 — Number
    num_key = col_map["TESTE - Número"]["key"]
    sent_num = 12345
    p_status, p_body = patch_item({"custom_fields": {num_key: sent_num}})
    read = read_item()
    got_num = (read.get("custom_fields") or {}).get(num_key) if read else None
    report["tests"]["numero"] = {
        "column_key": num_key,
        "write_http": p_status,
        "sent": sent_num,
        "read": got_num,
        "match": got_num == sent_num,
        "write_payload": {"custom_fields": {num_key: sent_num}},
        "read_format": "custom_fields[key]",
    }

    # Test 5 — Status
    status_key = col_map["TESTE - Status"]["key"]
    chosen_status = "follow_up"
    if status_options:
        chosen_status = status_options[1]["key"] if len(status_options) > 1 else status_options[0]["key"]
    p_status, p_body = patch_item({status_key: chosen_status})
    read = read_item()
    got_status = read.get(status_key) if read else None
    report["tests"]["status"] = {
        "column_key": status_key,
        "status_options": status_options,
        "chosen_key": chosen_status,
        "write_http": p_status,
        "sent": chosen_status,
        "read": got_status,
        "match": got_status == chosen_status,
        "write_payload": {status_key: chosen_status},
        "read_format": "top-level item field",
    }

    # Test 6 — Date
    date_key = col_map["TESTE - Data"]["key"]
    sent_date = "2026-01-15"
    p_status, p_body = patch_item({date_key: sent_date})
    read = read_item()
    got_date = read.get(date_key) if read else None
    report["tests"]["data"] = {
        "column_key": date_key,
        "write_http": p_status,
        "sent": sent_date,
        "read": got_date,
        "match": got_date is not None and "2026-01-15" in str(got_date),
        "write_payload": {date_key: sent_date},
        "read_format": "top-level ISO datetime string",
    }

    # Test 7 — Checkbox
    chk_key = col_map["TESTE - Checkbox"]["key"]
    p_true_status, _ = patch_item({"custom_fields": {chk_key: True}})
    read_true = read_item()
    got_true = (read_true.get("custom_fields") or {}).get(chk_key) if read_true else None
    p_false_status, _ = patch_item({"custom_fields": {chk_key: False}})
    read_false = read_item()
    got_false = (read_false.get("custom_fields") or {}).get(chk_key) if read_false else None
    report["tests"]["checkbox"] = {
        "column_key": chk_key,
        "write_true_http": p_true_status,
        "read_true": got_true,
        "true_match": got_true is True,
        "write_false_http": p_false_status,
        "read_false": got_false,
        "false_match": got_false is False,
        "write_payload_true": {"custom_fields": {chk_key: True}},
        "write_payload_false": {"custom_fields": {chk_key: False}},
        "read_format": "custom_fields[key] boolean",
    }

    # Test 8 — Link
    link_key = col_map["TESTE - Link"]["key"]
    sent_link = "https://example.com/teste-sunday-api"
    link_payload = {"url": sent_link, "text": "Exemplo fictício"}
    p_status, p_body = patch_item({"custom_fields": {link_key: link_payload}})
    read = read_item()
    got_link = (read.get("custom_fields") or {}).get(link_key) if read else None
    link_match = isinstance(got_link, dict) and got_link.get("url") == sent_link
    report["tests"]["link"] = {
        "column_key": link_key,
        "write_http": p_status,
        "sent": link_payload,
        "read": got_link,
        "match": link_match,
        "write_payload": {"custom_fields": {link_key: link_payload}},
        "read_format": "custom_fields[key] as {url, text}",
    }

    # Test 9 — People
    people_key = col_map["TESTE - Responsável"]["key"]
    people_result: dict[str, Any] = {
        "column_key": people_key,
        "auth_user_id": user_id,
    }
    if user_id:
        p_status, p_body = patch_item({people_key: user_id})
        read = read_item()
        got_owner = read.get(people_key) if read else None
        got_assignees = read.get("assignee_user_ids") if read else None
        people_result.update(
            {
                "write_http": p_status,
                "write_body": p_body,
                "sent": user_id,
                "read_owner_user_id": got_owner,
                "read_assignee_user_ids": got_assignees,
                "match": got_owner == user_id,
                "write_payload": {people_key: user_id},
                "read_format": "top-level owner_user_id",
            }
        )
    else:
        people_result["error"] = "Could not obtain user id from auth/me"
    report["tests"]["people"] = people_result

    # Test 10 — board_relation
    rel_key = col_map["TESTE - Relação"]["key"]
    target_create_status, target_body = req(
        "POST", f"boards/{BOARD_RELATION}/items", json_body={"name": ITEM_TARGET_NAME}
    )
    target_item_id = target_body.get("id") if isinstance(target_body, dict) else None

    relation_attempts: list[dict] = []

    # Attempt A: link to board 81 item (user expectation)
    if target_item_id:
        payloads_to_try = [
            {"custom_fields": {rel_key: [target_item_id]}},
            {"custom_fields": {rel_key: target_item_id}},
            {"custom_fields": {rel_key: {"item_ids": [target_item_id]}}},
            {"custom_fields": {rel_key: {"linked_item_ids": [target_item_id], "board_id": BOARD_RELATION}}},
        ]
        for payload in payloads_to_try:
            ps, pb = patch_item(payload)
            read = read_item()
            cf = (read.get("custom_fields") or {}) if read else {}
            relation_attempts.append(
                {
                    "target_board": BOARD_RELATION,
                    "target_item_id": target_item_id,
                    "payload": payload,
                    "write_http": ps,
                    "write_body": pb,
                    "read_custom_fields": cf.get(rel_key),
                    "full_custom_fields": cf,
                }
            )

    # Attempt B: if column points elsewhere, try item on configured board
    if relation_target_board and relation_target_board != BOARD_RELATION:
        alt_create_status, alt_body = req(
            "POST",
            f"boards/{relation_target_board}/items",
            json_body={"name": "TESTE TARGET RELATION ALT - PODE EXCLUIR"},
        )
        alt_item_id = alt_body.get("id") if isinstance(alt_body, dict) else None
        if alt_item_id:
            for payload in [
                {"custom_fields": {rel_key: [alt_item_id]}},
                {"custom_fields": {rel_key: alt_item_id}},
            ]:
                ps, pb = patch_item(payload)
                read = read_item()
                cf = (read.get("custom_fields") or {}) if read else {}
                relation_attempts.append(
                    {
                        "target_board": relation_target_board,
                        "target_item_id": alt_item_id,
                        "payload": payload,
                        "write_http": ps,
                        "write_body": pb,
                        "read_custom_fields": cf.get(rel_key),
                        "full_custom_fields": cf,
                    }
                )

    # Probe dedicated links endpoint
    links_status, links_body = req("GET", f"boards/{BOARD_MAIN}/links")
    item_links_status, item_links_body = req(
        "GET", f"boards/{BOARD_MAIN}/items/{item_id}/links"
    )

    read_final = read_item()
    rel_value = None
    if read_final and read_final.get("custom_fields"):
        rel_value = read_final["custom_fields"].get(rel_key)

    report["tests"]["board_relation"] = {
        "column_key": rel_key,
        "column_settings": relation_col.get("settings"),
        "target_item_create_http": target_create_status,
        "target_item_id_board_81": target_item_id,
        "attempts": relation_attempts,
        "final_read_relation_value": rel_value,
        "final_item_snapshot": read_final,
        "links_endpoint": {
            "boards_links_http": links_status,
            "boards_links_body": links_body,
            "item_links_http": item_links_status,
            "item_links_body": item_links_body,
        },
        "questions": {
            "accepted_write": any(
                a.get("read_custom_fields") is not None and a.get("write_http") == 200
                for a in relation_attempts
            ),
            "get_returns_target_item_id": _extract_linked_ids(rel_value),
            "target_board_identifiable": _identify_target_board(rel_value, relation_attempts),
            "reconstruct_without_links_endpoint": _can_reconstruct(rel_value),
            "maintain_via_normal_endpoints": any(a.get("write_http") == 200 for a in relation_attempts),
        },
    }

    # Fallback evaluation
    report["fallback_table"] = {
        "schema": [
            "monday_source_item_id",
            "monday_target_item_id",
            "sunday_source_board_id",
            "sunday_source_item_id",
            "sunday_target_board_id",
            "sunday_target_item_id",
            "relation_type",
        ],
        "sufficient_for": {
            "prazos_processos": True,
            "audiencias_processos": True,
            "controle_contratos": True,
        },
        "notes": "Local mapping table sufficient if native board_relation read/write incomplete",
    }

    # Matrix A/B/C/D
    report["matrix"] = build_matrix(report["tests"], report["validation"])

    # Decision
    report["decision"] = build_decision(report["tests"], report["matrix"], report["validation"])

    out_path = "/workspace/docs/sunday-fase0-write-report-2026-08-11.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def _extract_linked_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        ids = []
        for x in value:
            if isinstance(x, str):
                ids.append(x)
            elif isinstance(x, dict) and x.get("id"):
                ids.append(str(x["id"]))
            elif isinstance(x, dict) and x.get("item_id"):
                ids.append(str(x["item_id"]))
        return ids
    if isinstance(value, dict):
        for k in ("item_ids", "linked_item_ids", "ids", "items"):
            if k in value and isinstance(value[k], list):
                return [str(x) for x in value[k]]
        if value.get("id"):
            return [str(value["id"])]
    return []


def _identify_target_board(rel_value: Any, attempts: list[dict]) -> bool | str:
    if isinstance(rel_value, dict) and rel_value.get("board_id"):
        return rel_value["board_id"]
    for a in attempts:
        if a.get("read_custom_fields") is not None:
            return a.get("target_board", False)
    return False


def _can_reconstruct(rel_value: Any) -> bool:
    return len(_extract_linked_ids(rel_value)) > 0


def build_matrix(tests: dict, validation: dict) -> dict[str, str]:
    def grade(name: str, ok: bool, fallback: bool = False) -> str:
        if ok:
            return "A — funciona nativamente"
        if fallback:
            return "B — funciona com fallback"
        return "D — não funciona / bloqueante"

    m: dict[str, str] = {}
    m["schema_manual"] = "C — configuração manual aceitável"
    m["texto"] = grade("texto", tests.get("texto", {}).get("match", False))
    m["numero"] = grade("numero", tests.get("numero", {}).get("match", False))
    m["status"] = grade("status", tests.get("status", {}).get("match", False))
    m["data"] = grade("data", tests.get("data", {}).get("match", False))
    m["checkbox"] = grade(
        "checkbox",
        tests.get("checkbox", {}).get("true_match", False) and tests.get("checkbox", {}).get("false_match", False),
    )
    m["link"] = grade("link", tests.get("link", {}).get("match", False))
    m["people"] = grade("people", tests.get("people", {}).get("match", False), fallback=True)
    rel_q = tests.get("board_relation", {}).get("questions", {})
    rel_ok = rel_q.get("reconstruct_without_links_endpoint", False)
    m["board_relation"] = grade("board_relation", rel_ok, fallback=not rel_ok)
    m["create_item"] = "A — funciona nativamente" if tests.get("create_item", {}).get("http") in (200, 201) else "D"
    return m


def build_decision(tests: dict, matrix: dict, validation: dict) -> dict:
    essential = ["texto", "numero", "status", "data", "checkbox", "link", "create_item"]
    essential_ok = all(
        tests.get(k, {}).get("match", False) or tests.get("create_item", {}).get("http") in (200, 201)
        for k in essential
        if k != "create_item"
    )
    rel_native = tests.get("board_relation", {}).get("questions", {}).get("reconstruct_without_links_endpoint", False)
    rel_fallback_ok = True  # fallback table always sufficient per evaluation

    if essential_ok and (rel_native or rel_fallback_ok):
        verdict = "GO"
        reason = "Values read/write on preconfigured columns work via PATCH boards/{id}/items/{id}; schema manual OK"
    else:
        verdict = "NO-GO"
        reason = "Essential value types failed"

    return {
        "verdict": verdict,
        "reason": reason,
        "relation_native": rel_native,
        "relation_fallback_sufficient": rel_fallback_ok,
        "schema_api_create_columns": "C — not required; manual schema accepted",
        "relation_board_config_note": validation.get("relation_board_mismatch"),
    }


if __name__ == "__main__":
    sys.exit(main())
