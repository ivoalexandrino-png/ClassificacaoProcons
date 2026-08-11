#!/usr/bin/env python3
"""Fase 0 — reteste focado em *values* e *board_relation* no sandbox do Sunday.

Contexto: o teste de escrita anterior (F0.14) mostrou que o token de API **não cria
colunas** (``POST /boards/{id}/columns`` → 403). A decisão de arquitetura passou a ser:
o *schema* dos boards é configurado manualmente no Sunday e o adapter só manipula
*dados*. Este reteste responde de forma definitiva à pergunta que ficou em aberto:

    o token consegue GRAVAR e LER *values* de colunas já configuradas — inclusive
    ``board_relation`` — usando apenas os endpoints normais de itens/values?

O reteste **não** repete a Fase 0 inteira. Ele exercita só os Testes 1..10 pedidos,
100% sobre recursos fictícios criados aqui, e exclusivamente nos boards de sandbox
autorizados (80 e 81). Board 79 nunca é escrito — é apenas referenciado (leitura) porque
a coluna ``TESTE - RELAÇÃO`` foi configurada apontando para ele.

Guard-rails:
- Preflight confere o nome do board 80 antes de qualquer mutação.
- Escrita só é permitida em ``/boards/80/*``, ``/boards/81/*`` e em itens criados aqui.
- Dados 100% fictícios; nenhuma alteração no Monday.
- O token nunca é impresso nem gravado. A identidade do usuário autenticado é redigida
  no relatório persistido.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

SANDBOX_BOARD_ID = "80"
SANDBOX_BOARD_NAME = "SANDBOX - API SUNDAY - NÃO USAR"
RELATION_BOARD_ID = "81"  # board de sandbox autorizado para escrita
FICT_ITEM_NAME = "TESTE VALUES API - PODE EXCLUIR"

REPORT: list[dict] = []
FINDINGS: dict[str, object] = {}
OWNED_ITEMS: set[str] = set()
REDACT: set[str] = set()

# Boards em que a escrita é autorizada por este reteste.
WRITE_BOARDS = {SANDBOX_BOARD_ID, RELATION_BOARD_ID}


def _token() -> str:
    token = os.environ.get("SUNDAY_API_TOKEN", "").strip()
    if not token:
        print("ERRO: SUNDAY_API_TOKEN ausente.", file=sys.stderr)
        sys.exit(2)
    REDACT.add(token)
    return token


def _base() -> str:
    url = os.environ.get("SUNDAY_API_URL", "").strip()
    if not url:
        print("ERRO: SUNDAY_API_URL ausente.", file=sys.stderr)
        sys.exit(2)
    return url.rstrip("/")


def _assert_write_allowed(method: str, path: str) -> None:
    """Bloqueia qualquer escrita fora dos sandboxes 80/81 e dos itens criados aqui."""
    if method == "GET":
        return
    parts = [p for p in path.split("?")[0].split("/") if p]
    # /boards/{80|81}/...  → criação de item/grupo no sandbox autorizado
    if parts[:1] == ["boards"] and len(parts) >= 2 and parts[1] in WRITE_BOARDS:
        return
    # /boards/items/{id}[/...]  → só itens criados por este reteste
    if parts[:2] == ["boards", "items"] and len(parts) >= 3 and parts[2] in OWNED_ITEMS:
        return
    raise RuntimeError(f"Guard-rail: escrita bloqueada {method} {path}")


def api(method: str, path: str, body: object | None = None, note: str = "") -> tuple[int, object]:
    _assert_write_allowed(method, path)
    headers = {"X-Sunday-Token": _token()}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{_base()}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status, text = response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status, text = exc.code, exc.read().decode("utf-8", "replace")
    try:
        payload: object = json.loads(text) if text else None
    except json.JSONDecodeError:
        payload = text[:400]
    REPORT.append(
        {
            "note": note,
            "method": method,
            "path": path,
            "request_body": body,
            "status": status,
            "response": payload,
        },
    )
    print(f"[{status}] {method} {path}  {note}")
    return status, payload


def _value_of(values: object, column_id: str) -> object:
    """Extrai o value de uma coluna a partir de GET /boards/items/{id}/values."""
    if isinstance(values, list):
        for entry in values:
            if isinstance(entry, dict) and str(entry.get("column_id")) == str(column_id):
                return entry.get("value")
    return None


def _item_by_id(items: object, item_id: str) -> dict | None:
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and str(it.get("id")) == str(item_id):
                return it
    return None


# Chaves que carregam identidade de usuário (PII) fora de /auth/me e são redigidas.
# (o corpo de /auth/me é colapsado por inteiro; aqui tratamos os IDs em objetos de item)
SENSITIVE_KEYS = {
    "owner_user_id",
    "creator_user_id",
    "linked_user_id",
    "updated_by_user",
    "assignee_user_ids",
    "manager_user_id",
}

IDENTITY_PLACEHOLDER = "<omitido: identidade>"


def _redact(obj: object, key: str | None = None) -> object:
    """Redige token, identidade do usuário e campos de PII no relatório persistido."""
    if key in SENSITIVE_KEYS and obj is not None:
        return IDENTITY_PLACEHOLDER
    if isinstance(obj, str):
        return "<omitido: sensível>" if obj in REDACT and obj else obj
    if isinstance(obj, dict):
        # a resposta de /auth/me é toda PII → colapsa num único marcador
        if {"user_type", "hierarchy_level"} <= set(obj.keys()):
            return "<omitido: dados de identidade do usuário>"
        return {k: _redact(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v, key) for v in obj]
    return obj


def main() -> int:
    # ---- Preflight -----------------------------------------------------------------
    status, board = api("GET", f"/boards/{SANDBOX_BOARD_ID}", note="preflight board 80")
    if not isinstance(board, dict) or board.get("name") != SANDBOX_BOARD_NAME:
        print("ABORTADO: board 80 não é o sandbox esperado.", file=sys.stderr)
        return 2
    status_set = board.get("status_set") if isinstance(board, dict) else None
    FINDINGS["status_set"] = status_set

    status, me = api("GET", "/auth/me", note="identidade do token (redigida no relatório)")
    me_id = str(me.get("id", "")) if isinstance(me, dict) else ""
    if me_id:
        REDACT.add(me_id)
    for key in ("name", "display_name", "email"):
        val = me.get(key) if isinstance(me, dict) else None
        if isinstance(val, str) and val:
            REDACT.add(val)

    # ---- TESTE 1: descobrir column IDs --------------------------------------------
    status, cols = api("GET", f"/boards/{SANDBOX_BOARD_ID}/columns", note="T1 colunas do board 80")
    if not isinstance(cols, list):
        print("ABORTADO: não leu colunas do board 80.", file=sys.stderr)
        return 2
    by_key = {c["key"]: c for c in cols if isinstance(c, dict)}
    by_label = {(c.get("label") or "").strip().lower(): c for c in cols if isinstance(c, dict)}
    FINDINGS["columns"] = [
        {
            "id": c["id"],
            "key": c["key"],
            "type": c["type"],
            "label": c["label"],
            "is_system": c.get("is_system"),
            "settings": c.get("settings"),
        }
        for c in cols
        if isinstance(c, dict)
    ]

    def col(label_prefix: str) -> dict | None:
        for label, c in by_label.items():
            if label.startswith(label_prefix.lower()):
                return c
        return None

    col_texto = col("teste - texto") or by_key.get("name")
    col_numero = col("teste - número") or col("teste - numero")
    col_status = col("teste - status") or by_key.get("status")
    col_data = col("teste - data") or by_key.get("target_date")
    col_resp = col("teste - responsável") or col("teste - responsavel") or by_key.get("owner")
    col_link = col("teste - link")
    col_check = col("teste - checkbox")
    col_rel = col("teste - relação") or col("teste - relacao")

    required = {
        "TESTE - Texto": col_texto,
        "TESTE - Número": col_numero,
        "TESTE - Status": col_status,
        "TESTE - Data": col_data,
        "TESTE - Responsável": col_resp,
        "TESTE - Link": col_link,
        "TESTE - Checkbox": col_check,
        "TESTE - Relação": col_rel,
    }
    missing = [name for name, c in required.items() if not c]
    FINDINGS["required_columns_missing"] = missing
    if missing:
        print(f"PARE: colunas ausentes: {missing}", file=sys.stderr)
        FINDINGS["aborted"] = f"colunas ausentes: {missing}"
        _dump()
        return 3

    FINDINGS["column_ids"] = {name: c["id"] for name, c in required.items()}
    FINDINGS["column_kinds"] = {
        name: {"id": c["id"], "key": c["key"], "type": c["type"], "is_system": c.get("is_system")}
        for name, c in required.items()
    }
    rel_settings = col_rel.get("settings") if isinstance(col_rel, dict) else None
    FINDINGS["relation_column_settings"] = rel_settings

    # ---- TESTE 2: item fictício ----------------------------------------------------
    status, payload = api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/items",
        {"name": FICT_ITEM_NAME},
        note="T2 cria item fictício",
    )
    item = str(payload["id"]) if isinstance(payload, dict) and payload.get("id") else ""
    if not item:
        print("ABORTADO: não criou item fictício.", file=sys.stderr)
        return 2
    OWNED_ITEMS.add(item)
    FINDINGS["item_id"] = item

    is_system = {name: bool(c.get("is_system")) for name, c in required.items()}

    # ---- TESTE 3: Texto ------------------------------------------------------------
    # A coluna "TESTE - Texto" é a coluna de sistema `name` (texto). System columns são
    # gravadas via PATCH /boards/items/{id}; o endpoint de values as recusa (400).
    if is_system["TESTE - Texto"]:
        api(
            "PATCH",
            f"/boards/items/{item}/values/{col_texto['id']}",
            {"value": "Teste Sunday API"},
            note="T3 (control) values em coluna de sistema texto → espera 400",
        )
        api(
            "PATCH",
            f"/boards/items/{item}",
            {"name": "Teste Sunday API"},
            note="T3 grava texto via campo de sistema name",
        )
        _, items = api("GET", f"/boards/{SANDBOX_BOARD_ID}/items", note="T3 relê itens")
        got = (_item_by_id(items, item) or {}).get("name")
        FINDINGS["texto"] = {
            "column_is_system_name": True,
            "sent": "Teste Sunday API",
            "read_back": got,
            "match": got == "Teste Sunday API",
            "write_route": "PATCH /boards/items/{id} (campo name)",
        }
        # devolve o nome identificável/deletável
        api(
            "PATCH",
            f"/boards/items/{item}",
            {"name": FICT_ITEM_NAME},
            note="T3 restaura nome identificável do item",
        )
    else:
        api(
            "PATCH",
            f"/boards/items/{item}/values/{col_texto['id']}",
            {"value": "Teste Sunday API"},
            note="T3 grava texto via values",
        )
        _, vals = api("GET", f"/boards/items/{item}/values", note="T3 relê values")
        got = _value_of(vals, col_texto["id"])
        FINDINGS["texto"] = {
            "column_is_system_name": False,
            "sent": "Teste Sunday API",
            "read_back": got,
            "match": got == "Teste Sunday API",
            "write_route": "PATCH /boards/items/{id}/values/{col}",
        }

    # ---- TESTE 4: Número -----------------------------------------------------------
    api(
        "PATCH",
        f"/boards/items/{item}/values/{col_numero['id']}",
        {"value": 12345},
        note="T4 grava número via values",
    )
    _, vals = api("GET", f"/boards/items/{item}/values", note="T4 relê values")
    got = _value_of(vals, col_numero["id"])
    FINDINGS["numero"] = {
        "sent": 12345,
        "read_back": got,
        "read_back_type": type(got).__name__,
        "match": got == 12345,
        "write_route": "PATCH /boards/items/{id}/values/{col}",
    }

    # ---- TESTE 5: Status -----------------------------------------------------------
    keys = [s.get("key") for s in status_set] if isinstance(status_set, list) else []
    chosen = "follow_up" if "follow_up" in keys else (keys[0] if keys else None)
    FINDINGS["status_keys"] = keys
    FINDINGS["status_chosen"] = chosen
    if is_system["TESTE - Status"]:
        api(
            "PATCH",
            f"/boards/items/{item}/values/{col_status['id']}",
            {"value": chosen},
            note="T5 (control) values em coluna de sistema status → espera 400",
        )
        api(
            "PATCH",
            f"/boards/items/{item}/status",
            {"status": chosen, "cascade": False},
            note="T5 grava status via campo de sistema",
        )
        _, items = api("GET", f"/boards/{SANDBOX_BOARD_ID}/items", note="T5 relê itens")
        got = (_item_by_id(items, item) or {}).get("status")
        FINDINGS["status"] = {
            "column_is_system": True,
            "sent": chosen,
            "read_back": got,
            "match": got == chosen,
            "write_route": "PATCH /boards/items/{id}/status",
        }
    else:
        api(
            "PATCH",
            f"/boards/items/{item}/values/{col_status['id']}",
            {"value": chosen},
            note="T5 grava status via values",
        )
        _, vals = api("GET", f"/boards/items/{item}/values", note="T5 relê values")
        got = _value_of(vals, col_status["id"])
        FINDINGS["status"] = {
            "column_is_system": False,
            "sent": chosen,
            "read_back": got,
            "match": got == chosen,
            "write_route": "PATCH /boards/items/{id}/values/{col}",
        }

    # ---- TESTE 6: Data -------------------------------------------------------------
    if is_system["TESTE - Data"]:
        api(
            "PATCH",
            f"/boards/items/{item}/values/{col_data['id']}",
            {"value": "2026-01-15"},
            note="T6 (control) values em coluna de sistema date → espera 400",
        )
        api(
            "PATCH",
            f"/boards/items/{item}",
            {"target_date": "2026-01-15"},
            note="T6 grava data via campo de sistema target_date",
        )
        _, items = api("GET", f"/boards/{SANDBOX_BOARD_ID}/items", note="T6 relê itens")
        got = (_item_by_id(items, item) or {}).get("target_date")
        FINDINGS["data"] = {
            "column_is_system": True,
            "sent": "2026-01-15",
            "read_back": got,
            "write_route": "PATCH /boards/items/{id} (target_date)",
        }
    else:
        api(
            "PATCH",
            f"/boards/items/{item}/values/{col_data['id']}",
            {"value": "2026-01-15"},
            note="T6 grava data via values",
        )
        _, vals = api("GET", f"/boards/items/{item}/values", note="T6 relê values")
        got = _value_of(vals, col_data["id"])
        FINDINGS["data"] = {
            "column_is_system": False,
            "sent": "2026-01-15",
            "read_back": got,
            "write_route": "PATCH /boards/items/{id}/values/{col}",
        }

    # ---- TESTE 7: Checkbox ---------------------------------------------------------
    api(
        "PATCH",
        f"/boards/items/{item}/values/{col_check['id']}",
        {"value": True},
        note="T7 grava checkbox true",
    )
    _, vals = api("GET", f"/boards/items/{item}/values", note="T7 relê values (true)")
    got_true = _value_of(vals, col_check["id"])
    api(
        "PATCH",
        f"/boards/items/{item}/values/{col_check['id']}",
        {"value": False},
        note="T7 grava checkbox false",
    )
    _, vals = api("GET", f"/boards/items/{item}/values", note="T7 relê values (false)")
    got_false = _value_of(vals, col_check["id"])
    FINDINGS["checkbox"] = {
        "true": {"read_back": got_true, "match": got_true is True},
        "false": {"read_back": got_false, "match": got_false is False},
        "write_route": "PATCH /boards/items/{id}/values/{col}",
    }

    # ---- TESTE 8: Link -------------------------------------------------------------
    link_url = "https://example.com/teste-sunday-api"
    api(
        "PATCH",
        f"/boards/items/{item}/values/{col_link['id']}",
        {"value": link_url},
        note="T8 grava link via values",
    )
    _, vals = api("GET", f"/boards/items/{item}/values", note="T8 relê values")
    got = _value_of(vals, col_link["id"])
    FINDINGS["link"] = {
        "sent": link_url,
        "read_back": got,
        "match": got == link_url,
        "write_route": "PATCH /boards/items/{id}/values/{col}",
    }

    # ---- TESTE 9: People (não bloqueante) -----------------------------------------
    people = {"user_id_source": "GET /auth/me"}
    if me_id:
        s_sys, r_sys = api(
            "PATCH",
            f"/boards/items/{item}/values/{col_resp['id']}",
            {"value": me_id},
            note="T9 (control) values em coluna de sistema people → espera 400",
        )
        s_own, r_own = api(
            "PATCH",
            f"/boards/items/{item}",
            {"owner_user_id": me_id},
            note="T9 grava responsável via campo de sistema owner_user_id",
        )
        _, items = api("GET", f"/boards/{SANDBOX_BOARD_ID}/items", note="T9 relê itens")
        it = _item_by_id(items, item) or {}
        read_owner = it.get("owner_user_id")
        people.update(
            {
                "values_route_status": s_sys,
                "values_route_body": r_sys,
                "system_route_status": s_own,
                "write_ok": s_own == 200,
                "read_back_matches": str(read_owner) == me_id if read_owner is not None else None,
                "write_route": "PATCH /boards/items/{id} (owner_user_id)",
            }
        )
    else:
        people["error"] = "GET /auth/me não retornou id de usuário"
    FINDINGS["people"] = people

    # ---- TESTE 10: board_relation --------------------------------------------------
    relation: dict[str, object] = {"column_id": col_rel["id"], "column_settings": rel_settings}
    configured_target_board = None
    if isinstance(rel_settings, dict):
        configured_target_board = str(rel_settings.get("source_board_id") or "") or None
    relation["configured_target_board_id"] = configured_target_board

    # 10.a — alvo no board 81 (autorizado). Testa se a API valida o board conectado.
    s, payload = api(
        "POST",
        f"/boards/{RELATION_BOARD_ID}/items",
        {"name": "TESTE TARGET RELATION - PODE EXCLUIR"},
        note="T10 cria item alvo no board 81",
    )
    target81 = str(payload["id"]) if isinstance(payload, dict) and payload.get("id") else ""
    relation["target_item_board81"] = target81

    def try_relation(target_id: str, label: str) -> dict:
        attempts = []
        # formato documentado {links:[{item_id,label}]}
        s1, r1 = api(
            "PATCH",
            f"/boards/items/{item}/values/{col_rel['id']}",
            {"value": {"links": [{"item_id": target_id}]}},
            note=f"T10 relação → {label}: value={{links:[{{item_id}}]}}",
        )
        attempts.append({"format": "{links:[{item_id}]}", "status": s1, "response": r1})
        _, vals = api(
            "GET",
            f"/boards/items/{item}/values",
            note=f"T10 relê values após {label} (dict)",
        )
        read_dict = _value_of(vals, col_rel["id"])
        # formato bare string (item_id)
        s2, r2 = api(
            "PATCH",
            f"/boards/items/{item}/values/{col_rel['id']}",
            {"value": target_id},
            note=f"T10 relação → {label}: value=<item_id> (string)",
        )
        attempts.append({"format": "<item_id> string", "status": s2, "response": r2})
        _, vals = api(
            "GET",
            f"/boards/items/{item}/values",
            note=f"T10 relê values após {label} (string)",
        )
        read_str = _value_of(vals, col_rel["id"])
        return {
            "target_id": target_id,
            "attempts": attempts,
            "read_back_after_dict": read_dict,
            "read_back_after_string": read_str,
            "accepted": s1 < 300 or s2 < 300,
        }

    # 10.a alvo em board 81 (não é o board conectado 79)
    if target81:
        relation["target_board81"] = try_relation(target81, "board 81 (não conectado)")

    # 10.b alvo no board conectado (79). NÃO escrevemos no board 79: apenas referenciamos
    # um item fictício preexistente ("PODE EXCLUIR"), se houver, para o caminho feliz.
    if configured_target_board and configured_target_board not in WRITE_BOARDS:
        _, target_items = api(
            "GET",
            f"/boards/{configured_target_board}/items",
            note=f"T10 lê itens do board conectado {configured_target_board} (só leitura)",
        )
        candidate = None
        if isinstance(target_items, list):
            for it in target_items:
                nm = (it.get("name") or "") if isinstance(it, dict) else ""
                if "PODE EXCLUIR" in nm or "TESTE" in nm.upper():
                    candidate = str(it.get("id"))
                    break
        relation["configured_board_candidate_item"] = candidate
        if candidate:
            # snapshot dos values do alvo antes/depois → detecta espelho recíproco
            _, pre = api(
                "GET",
                f"/boards/items/{candidate}/values",
                note="T10 pré-leitura do alvo (detecta espelho recíproco)",
            )
            relation["target_connected"] = try_relation(
                candidate, f"board {configured_target_board} (conectado)"
            )
            _, post = api(
                "GET",
                f"/boards/items/{candidate}/values",
                note="T10 pós-leitura do alvo (detecta espelho recíproco)",
            )
            relation["reciprocal_write_on_target"] = post != pre
            relation["target_values_before"] = pre
            relation["target_values_after"] = post

    FINDINGS["board_relation"] = relation

    _dump()
    return 0


def _dump() -> None:
    default_report = "docs/sunday-fase0-values-report-2026-08-11.json"
    out_report = os.environ.get("SUNDAY_RETEST_REPORT", default_report)
    payload = {"findings": _redact(FINDINGS), "steps": _redact(REPORT)}
    with open(out_report, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
    print(f"\nRelatório: {out_report} ({len(REPORT)} passos)")


if __name__ == "__main__":
    sys.exit(main())
