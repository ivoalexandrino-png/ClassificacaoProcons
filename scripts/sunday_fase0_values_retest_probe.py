#!/usr/bin/env python3
"""Fase 0 — sonda complementar do reteste de values (sandbox 80/81).

Fecha três lacunas do reteste principal (`sunday_fase0_values_retest.py`):

1. status: `PATCH /boards/items/{id}` com `{"status": ...}` devolve 200 mas NÃO altera;
   confirma a rota dedicada `PATCH /boards/items/{id}/status` (formato da 1ª rodada);
2. people: o owner já nasce igual ao usuário do token, então o PATCH anterior foi
   inconclusivo — testa owner_user_id null → me → releitura em item novo;
3. board_relation: o reteste gravou um único id (string); testa lista de ids
   (one-to-many, necessário p/ Controle Assinaturas → Contratos) e restaura o valor.

Mesmos guard-rails: escrita apenas nos boards 80/81 e em itens criados pelos testes.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

SANDBOX_BOARD_ID = "80"
SANDBOX_BOARD_NAME = "SANDBOX - API SUNDAY - NÃO USAR"
RELATION_BOARD_ID = "81"
RELATION_COLUMN_ID = "456"
MAIN_ITEM_NAME = "TESTE VALUES API - PODE EXCLUIR"
MAIN_TARGET_NAME = "TESTE TARGET RELATION - PODE EXCLUIR"

REPORT: list[dict] = []
OWNED_ITEMS: set[str] = set()
SENSITIVE: set[str] = set()


def _token() -> str:
    return os.environ["SUNDAY_API_TOKEN"].strip()


def _base() -> str:
    return os.environ["SUNDAY_API_URL"].strip().rstrip("/")


def _assert_write_allowed(method: str, path: str) -> None:
    if method == "GET":
        return
    parts = [p for p in path.split("?")[0].split("/") if p]
    if parts[:2] in (["boards", SANDBOX_BOARD_ID], ["boards", RELATION_BOARD_ID]):
        return
    if parts[:2] == ["boards", "items"] and len(parts) >= 3 and parts[2] in OWNED_ITEMS:
        return
    raise RuntimeError(f"Guard-rail: escrita bloqueada {method} {path}")


def api(method: str, path: str, body: dict | None = None, note: str = "") -> tuple[int, object]:
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
        payload = json.loads(text) if text else None
    except json.JSONDecodeError:
        payload = text[:400]
    REPORT.append(
        {"note": note, "method": method, "path": path, "request_body": body,
         "status": status, "response": payload},
    )
    print(f"[{status}] {method} {path}  {note}")
    return status, payload


def _sanitize(obj: object) -> object:
    """Omite identidade sem corromper strings vizinhas: ids curtos só por igualdade
    exata (ou entre aspas, caso de previews JSON); substring só para segredos longos
    (e-mail/nome)."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, str):
        placeholder = "<omitido: id de usuário>"
        if obj in SENSITIVE:
            return placeholder
        for secret in SENSITIVE:
            if not secret:
                continue
            if len(secret) >= 6 and secret in obj:
                obj = obj.replace(secret, placeholder)
            elif f'"{secret}"' in obj:
                obj = obj.replace(f'"{secret}"', f'"{placeholder}"')
        return obj
    return obj


def _find_item(items: object, name: str, board_id: str) -> str:
    if isinstance(items, list):
        for entry in items:
            if entry.get("name") == name and str(entry.get("board_id")) == board_id:
                return str(entry["id"])
    return ""


def main() -> int:
    _, board80 = api("GET", f"/boards/{SANDBOX_BOARD_ID}", note="preflight board 80")
    if not isinstance(board80, dict) or board80.get("name") != SANDBOX_BOARD_NAME:
        print("ABORTADO: board 80 não é o sandbox esperado.", file=sys.stderr)
        return 2
    _, me = api("GET", "/auth/me", note="identidade do token")
    me_id = str(me.get("id", "")) if isinstance(me, dict) else ""
    if isinstance(me, dict):
        for key in ("id", "email", "name", "display_name"):
            if me.get(key):
                SENSITIVE.add(str(me[key]))
        REPORT[-1]["response"] = "<omitido: dados de identidade>"

    _, items80 = api("GET", f"/boards/{SANDBOX_BOARD_ID}/items", note="itens do board 80")
    REPORT[-1]["response"] = "<omitido: lista completa>"
    main_item = _find_item(items80, MAIN_ITEM_NAME, SANDBOX_BOARD_ID)
    _, items81 = api("GET", f"/boards/{RELATION_BOARD_ID}/items", note="itens do board 81")
    REPORT[-1]["response"] = "<omitido: lista completa>"
    main_target = _find_item(items81, MAIN_TARGET_NAME, RELATION_BOARD_ID)
    if not main_item or not main_target:
        print("ABORTADO: itens do reteste principal não encontrados.", file=sys.stderr)
        return 2
    OWNED_ITEMS.update({main_item, main_target})

    # P1 — status pela rota dedicada (PATCH item com {"status"} é ignorado em silêncio)
    api("PATCH", f"/boards/items/{main_item}", {"status": "follow_up"},
        note="P1 status: PATCH item (confirma que é ignorado)")
    api("PATCH", f"/boards/items/{main_item}/status", {"status": "follow_up", "cascade": False},
        note="P1 status: rota dedicada /status")

    # P2 — people definitivo: item novo, owner null → me → releitura
    _, payload = api(
        "POST", f"/boards/{SANDBOX_BOARD_ID}/items",
        {"name": "TESTE PEOPLE API - PODE EXCLUIR"},
        note="P2 people: cria item novo (owner de fábrica?)",
    )
    people_item = str(payload["id"]) if isinstance(payload, dict) and payload.get("id") else ""
    if people_item:
        OWNED_ITEMS.add(people_item)
        api("PATCH", f"/boards/items/{people_item}", {"owner_user_id": None},
            note="P2 people: limpa owner (null)")
        api("PATCH", f"/boards/items/{people_item}", {"owner_user_id": me_id},
            note="P2 people: define owner = usuário do token")
        api("PATCH", f"/boards/items/{people_item}", {"assignee_user_ids": [me_id]},
            note="P2 people: assignee_user_ids (aceito ou ignorado?)")

    # P3 — board_relation com lista de ids (one-to-many)
    _, payload = api(
        "POST", f"/boards/{RELATION_BOARD_ID}/items",
        {"name": "TESTE TARGET RELATION 2 - PODE EXCLUIR"},
        note="P3 relação: cria 2º item alvo no board 81",
    )
    target2 = str(payload["id"]) if isinstance(payload, dict) and payload.get("id") else ""
    if target2:
        OWNED_ITEMS.add(target2)
        api("PATCH", f"/boards/items/{main_item}/values/{RELATION_COLUMN_ID}",
            {"value": [main_target, target2]},
            note="P3 relação: grava LISTA de item_ids")
        api("GET", f"/boards/items/{main_item}/values", note="P3 relação: relê values (lista)")
        api("PATCH", f"/boards/items/{main_item}/values/{RELATION_COLUMN_ID}",
            {"value": None},
            note="P3 relação: limpa a relação (null)")
        api("GET", f"/boards/items/{main_item}/values", note="P3 relação: relê values (null)")
        api("PATCH", f"/boards/items/{main_item}/values/{RELATION_COLUMN_ID}",
            {"value": main_target},
            note="P3 relação: restaura valor único original")

    # Releitura final consolidada
    api("GET", f"/boards/items/{main_item}/values", note="final: values do item principal")
    _, items80 = api("GET", f"/boards/{SANDBOX_BOARD_ID}/items", note="final: itens do board 80")
    if isinstance(items80, list):
        keep = [i for i in items80 if str(i.get("id")) in OWNED_ITEMS]
        REPORT[-1]["response"] = keep

    out = "/tmp/sunday-values-retest-probe-report.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(_sanitize(REPORT), handle, ensure_ascii=False, indent=2, default=str)
    print(f"\nRelatório: {out} ({len(REPORT)} passos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
