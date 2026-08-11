#!/usr/bin/env python3
"""Fase 0 — follow-up dos testes de escrita (fecha lacunas deixadas pelo escopo do token).

A primeira execução de `sunday_fase0_write_tests.py` mostrou que POST /boards/{id}/columns
é 403 ("configuração exige login"), então o PATCH de values nunca chegou a testar uma
coluna real. Este follow-up testa, SOMENTE no sandbox 80 e em recursos criados aqui:

- PATCH /boards/items/{id}/values/{col} contra as colunas de SISTEMA (name/status/
  owner/target_date/area) — para saber se o endpoint de values funciona de fato;
- PATCH /boards/items/{id} com campos diretos (target_date, area, assignee_user_ids,
  group_id) — formato alternativo de escrita;
- DELETE /boards/items/{id} e DELETE /boards/groups/{id} (o "D" do CRUD);
- GET de item individual (rota a confirmar).

Guard-rails idênticos ao script principal: preflight confere o nome do board 80;
mutações só em recursos criados por este script; dados 100% fictícios; token nunca
impresso nem gravado no relatório.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

SANDBOX_BOARD_ID = "80"
SANDBOX_BOARD_NAME = "SANDBOX - API SUNDAY - NÃO USAR"
FICT = "TESTE-FICTICIO"
REPORT: list[dict] = []
OWNED: dict[str, set[str]] = {"items": set(), "groups": set(), "attachments": set()}


def _token() -> str:
    token = os.environ.get("SUNDAY_API_TOKEN", "").strip()
    if not token:
        print("ERRO: SUNDAY_API_TOKEN ausente.", file=sys.stderr)
        sys.exit(2)
    return token


def _base() -> str:
    return os.environ["SUNDAY_API_URL"].strip().rstrip("/")


def _assert_write_allowed(method: str, path: str) -> None:
    if method == "GET":
        return
    parts = [p for p in path.split("?")[0].split("/") if p]
    if parts[:2] == ["boards", SANDBOX_BOARD_ID]:
        return
    if parts[:2] == ["boards", "items"] and len(parts) >= 3 and parts[2] in OWNED["items"]:
        return
    if parts[:2] == ["boards", "groups"] and len(parts) >= 3 and parts[2] in OWNED["groups"]:
        return
    if (
        parts[:2] == ["boards", "attachments"]
        and len(parts) >= 3
        and parts[2] in OWNED["attachments"]
    ):
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


def main() -> int:
    _, board = api("GET", f"/boards/{SANDBOX_BOARD_ID}", note="preflight sandbox")
    if not isinstance(board, dict) or board.get("name") != SANDBOX_BOARD_NAME:
        print("ABORTADO: board 80 não é o sandbox esperado.", file=sys.stderr)
        return 2
    _, me = api("GET", "/auth/me", note="usuário do token")
    me_id = str(me.get("id", "")) if isinstance(me, dict) else ""

    _, cols = api("GET", f"/boards/{SANDBOX_BOARD_ID}/columns", note="colunas de sistema")
    by_key = {c["key"]: c for c in cols if isinstance(c, dict)}

    _, payload = api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/groups",
        {"name": f"{FICT} Grupo follow-up", "color": "pink"},
        note="grupo para mover item",
    )
    group_id = str(payload["id"]) if isinstance(payload, dict) and payload.get("id") else ""
    if group_id:
        OWNED["groups"].add(group_id)

    _, payload = api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/items",
        {"name": f"{FICT} follow-up values"},
        note="item de teste de values",
    )
    item = str(payload["id"]) if isinstance(payload, dict) and payload.get("id") else ""
    if not item:
        print("ABORTADO: não criou item de teste.", file=sys.stderr)
        return 2
    OWNED["items"].add(item)

    # 1) endpoint de values contra colunas de sistema
    system_values = [
        ("name", "novo nome fictício via values"),
        ("status", "follow_up"),
        ("owner", me_id),
        ("target_date", "2026-03-15"),
        ("area", "ficticio"),
    ]
    for key, value in system_values:
        col = by_key.get(key)
        if col:
            api(
                "PATCH",
                f"/boards/items/{item}/values/{col['id']}",
                {"value": value},
                note=f"values na coluna de sistema {key} (id {col['id']})",
            )
    api("GET", f"/boards/items/{item}/values", note="relê values")

    # 2) campos diretos no PATCH do item
    api(
        "PATCH",
        f"/boards/items/{item}",
        {"target_date": "2026-04-01", "area": "ficticio-direto"},
        note="PATCH item com target_date/area diretos",
    )
    api(
        "PATCH",
        f"/boards/items/{item}",
        {"assignee_user_ids": [me_id], "owner_user_id": me_id},
        note="PATCH item com responsáveis diretos",
    )
    if group_id:
        api(
            "PATCH",
            f"/boards/items/{item}",
            {"group_id": group_id},
            note="PATCH item movendo de grupo (ignorado?)",
        )
        api(
            "PATCH",
            f"/boards/items/{item}/group",
            {"group_id": group_id},
            note="PATCH /group (rota documentada de mover)",
        )
    api("GET", f"/boards/items/{item}", note="GET item individual (rota a confirmar)")

    # links do board (candidato a suporte de board_relation)
    api("GET", f"/boards/{SANDBOX_BOARD_ID}/links", note="GET links do board")
    api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/links",
        {"target_board_id": "81"},
        note="POST link board 80→81 (payload especulativo)",
    )
    _, items = api("GET", f"/boards/{SANDBOX_BOARD_ID}/items", note="relê itens do board")
    if isinstance(items, list):
        mine = [i for i in items if str(i.get("id")) == item]
        REPORT.append({"note": "estado final do item de teste", "item": mine})

    # 3) DELETE (o "D" do CRUD)
    _, payload = api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/items",
        {"name": f"{FICT} para excluir"},
        note="item descartável p/ DELETE",
    )
    disposable = str(payload["id"]) if isinstance(payload, dict) and payload.get("id") else ""
    if disposable:
        OWNED["items"].add(disposable)
        api("DELETE", f"/boards/items/{disposable}", note="DELETE item")
        api("GET", f"/boards/items/{disposable}", note="GET item excluído (confirmação)")
    if group_id:
        api("DELETE", f"/boards/groups/{group_id}", note="DELETE grupo (esperado 403?)")

    # DELETE de anexo (anexo de link criado neste follow-up)
    _, payload = api(
        "POST",
        f"/boards/items/{item}/attachments/link",
        {"url": "https://example.com/anexo-followup", "filename": "anexo follow-up"},
        note="anexo de link p/ DELETE",
    )
    attachment_id = str(payload["id"]) if isinstance(payload, dict) and payload.get("id") else ""
    if attachment_id:
        OWNED["attachments"].add(attachment_id)
        api("DELETE", f"/boards/attachments/{attachment_id}", note="DELETE anexo")

    out = "/tmp/sunday-write-followup-report.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(REPORT, handle, ensure_ascii=False, indent=2, default=str)
    print(f"\nRelatório: {out} ({len(REPORT)} passos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
