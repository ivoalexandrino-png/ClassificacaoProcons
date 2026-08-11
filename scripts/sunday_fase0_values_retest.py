#!/usr/bin/env python3
"""Fase 0 — reteste de values e board_relation em colunas pré-configuradas (sandbox 80/81).

Contexto: o token não cria colunas (403) — decisão de arquitetura: schema manual no
Sunday, dados via adapter. As colunas TESTE-* foram criadas manualmente no board 80.
Este reteste verifica SOMENTE se o token grava e lê values dessas colunas, e se a
relação (board_relation) com o board 81 funciona pelos endpoints normais de values.

Guard-rails:
- escrita permitida apenas nos boards sandbox 80 e 81 e em itens criados aqui;
- o board 79 (Legal - Seguros, produção) NUNCA é referenciado em escrita;
- dados 100% fictícios; token e identidade nunca impressos nem gravados no relatório.
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request

SANDBOX_BOARD_ID = "80"
SANDBOX_BOARD_NAME = "SANDBOX - API SUNDAY - NÃO USAR"
RELATION_BOARD_ID = "81"
RELATION_BOARD_NAME = "SANDBOX - API SUNDAY - RELATION"
FORBIDDEN_BOARD_IDS = {"79"}
ITEM_NAME = "TESTE VALUES API - PODE EXCLUIR"
TARGET_ITEM_NAME = "TESTE TARGET RELATION - PODE EXCLUIR"

REPORT: list[dict] = []
OWNED_ITEMS: set[str] = set()
SENSITIVE: set[str] = set()

REQUIRED_COLUMNS = {
    "texto": "TESTE - Texto",
    "numero": "TESTE - Número",
    "status": "TESTE - Status",
    "data": "TESTE - Data",
    "responsavel": "TESTE - Responsável",
    "link": "TESTE - Link",
    "checkbox": "TESTE - Checkbox",
    "relacao": "TESTE - Relação",
}


def _norm(label: str) -> str:
    text = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _token() -> str:
    token = os.environ.get("SUNDAY_API_TOKEN", "").strip()
    if not token:
        print("ERRO: SUNDAY_API_TOKEN ausente.", file=sys.stderr)
        sys.exit(2)
    return token


def _base() -> str:
    url = os.environ.get("SUNDAY_API_URL", "").strip().rstrip("/")
    if not url:
        print("ERRO: SUNDAY_API_URL ausente.", file=sys.stderr)
        sys.exit(2)
    return url


def _assert_write_allowed(method: str, path: str, body: dict | None) -> None:
    if method == "GET":
        return
    serialized = json.dumps(body or {})
    for forbidden in FORBIDDEN_BOARD_IDS:
        if f'"{forbidden}"' in serialized:
            raise RuntimeError(f"Guard-rail: payload referencia board proibido {forbidden}")
    parts = [p for p in path.split("?")[0].split("/") if p]
    if parts[:2] in (["boards", SANDBOX_BOARD_ID], ["boards", RELATION_BOARD_ID]):
        return
    if parts[:2] == ["boards", "items"] and len(parts) >= 3 and parts[2] in OWNED_ITEMS:
        return
    raise RuntimeError(f"Guard-rail: escrita bloqueada {method} {path}")


def api(method: str, path: str, body: dict | None = None, note: str = "") -> tuple[int, object]:
    _assert_write_allowed(method, path, body)
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


def read_values(item_id: str, note: str) -> object:
    _, payload = api("GET", f"/boards/items/{item_id}/values", note=note)
    return payload


def read_item(item_id: str, note: str) -> dict | None:
    _, items = api("GET", f"/boards/{SANDBOX_BOARD_ID}/items", note=note)
    if isinstance(items, list):
        for entry in items:
            if str(entry.get("id")) == item_id:
                REPORT.append({"note": f"{note} (item {item_id} extraído)", "item": entry})
                return entry
    return None


def try_values(item_id: str, column_id: str, candidates: list[object], label: str) -> bool:
    """PATCH values com formatos candidatos; para no primeiro 2xx."""
    for candidate in candidates:
        preview = json.dumps(candidate, ensure_ascii=False)[:80]
        status, _ = api(
            "PATCH",
            f"/boards/items/{item_id}/values/{column_id}",
            {"value": candidate},
            note=f"{label}: PATCH values (payload={preview})",
        )
        if 200 <= status < 300:
            return True
    return False


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
    if isinstance(obj, (int, float)) and str(obj) in SENSITIVE:
        return "<omitido: id de usuário>"
    return obj


def main() -> int:
    # Preflight: boards sandbox
    _, board80 = api("GET", f"/boards/{SANDBOX_BOARD_ID}", note="preflight board 80")
    if not isinstance(board80, dict) or board80.get("name") != SANDBOX_BOARD_NAME:
        print("ABORTADO: board 80 não é o sandbox esperado.", file=sys.stderr)
        return 2
    _, board81 = api("GET", f"/boards/{RELATION_BOARD_ID}", note="preflight board 81")
    if not isinstance(board81, dict) or board81.get("name") != RELATION_BOARD_NAME:
        print("ABORTADO: board 81 não é o sandbox RELATION esperado.", file=sys.stderr)
        return 2

    # Identidade (sanitizada no relatório)
    _, me = api("GET", "/auth/me", note="identidade do token")
    me_id = str(me.get("id", "")) if isinstance(me, dict) else ""
    if isinstance(me, dict):
        for key in ("id", "email", "name", "display_name"):
            value = me.get(key)
            if value:
                SENSITIVE.add(str(value))
        REPORT[-1]["response"] = "<omitido: dados de identidade>"

    # TESTE 1 — column IDs
    _, cols = api("GET", f"/boards/{SANDBOX_BOARD_ID}/columns", note="T1 colunas do board 80")
    by_norm = {_norm(c["label"]): c for c in cols if isinstance(c, dict)}
    mapping: dict[str, dict] = {}
    missing: list[str] = []
    for key, label in REQUIRED_COLUMNS.items():
        col = by_norm.get(_norm(label))
        if col is None:
            missing.append(label)
        else:
            mapping[key] = col
    if missing:
        print(f"PARADO: colunas ausentes no board 80: {missing}", file=sys.stderr)
        REPORT.append({"note": "colunas ausentes — teste interrompido", "missing": missing})
        return 3
    REPORT.append({
        "note": "T1 mapeamento nome → column_id → type → settings",
        "mapping": {
            REQUIRED_COLUMNS[k]: {
                "column_id": c["id"], "key": c.get("key"), "type": c["type"],
                "is_system": c.get("is_system"), "settings": c.get("settings"),
            }
            for k, c in mapping.items()
        },
    })
    relacao_settings = mapping["relacao"].get("settings") or {}
    if str(relacao_settings.get("source_board_id")) != RELATION_BOARD_ID:
        REPORT.append({
            "note": "AVISO: TESTE - Relação NÃO aponta para o board 81",
            "settings": relacao_settings,
        })

    # TESTE 2 — item fictício
    _, payload = api(
        "POST", f"/boards/{SANDBOX_BOARD_ID}/items", {"name": ITEM_NAME},
        note="T2 cria item fictício",
    )
    item = str(payload["id"]) if isinstance(payload, dict) and payload.get("id") else ""
    if not item:
        print("ABORTADO: não criou o item de teste.", file=sys.stderr)
        return 2
    OWNED_ITEMS.add(item)

    # TESTE 3 — texto ("TESTE - Texto" é a coluna de sistema name)
    texto = mapping["texto"]
    try_values(item, texto["id"], ["Teste Sunday API"], "T3 texto")
    if texto.get("is_system"):
        api("PATCH", f"/boards/items/{item}", {"name": "Teste Sunday API"},
            note="T3 texto: PATCH item (rota de coluna de sistema)")
    read_values(item, "T3 texto: relê values")
    read_item(item, "T3 texto: relê item")

    # TESTE 4 — número
    numero = mapping["numero"]
    try_values(item, numero["id"], [12345, "12345"], "T4 número")
    read_values(item, "T4 número: relê values")

    # TESTE 5 — status (descobrir keys reais antes de gravar)
    status_col = mapping["status"]
    status_keys = [
        s.get("key") for s in (board80.get("status_set") or []) if isinstance(s, dict)
    ]
    options = (status_col.get("settings") or {}).get("options") or []
    status_keys += [o.get("key") for o in options if isinstance(o, dict)]
    REPORT.append({"note": "T5 status: keys reais descobertas", "keys": status_keys})
    chosen = next((k for k in status_keys if k and k != "to_do"), None)
    if chosen:
        try_values(item, status_col["id"], [chosen], "T5 status")
        if status_col.get("is_system"):
            api("PATCH", f"/boards/items/{item}", {"status": chosen},
                note=f"T5 status: PATCH item (key existente {chosen})")
    read_values(item, "T5 status: relê values")
    read_item(item, "T5 status: relê item")

    # TESTE 6 — data
    data_col = mapping["data"]
    try_values(item, data_col["id"], ["2026-01-15"], "T6 data")
    if data_col.get("is_system"):
        api("PATCH", f"/boards/items/{item}", {"target_date": "2026-01-15"},
            note="T6 data: PATCH item (rota de coluna de sistema)")
    read_values(item, "T6 data: relê values")
    read_item(item, "T6 data: relê item")

    # TESTE 7 — checkbox (true → lê → false → lê)
    checkbox = mapping["checkbox"]
    try_values(item, checkbox["id"], [True], "T7 checkbox true")
    read_values(item, "T7 checkbox: relê values (true)")
    try_values(item, checkbox["id"], [False], "T7 checkbox false")
    read_values(item, "T7 checkbox: relê values (false)")

    # TESTE 8 — link
    link = mapping["link"]
    ok = try_values(item, link["id"], ["https://example.com/teste-sunday-api"], "T8 link")
    if not ok:
        try_values(
            item, link["id"],
            [{"url": "https://example.com/teste-sunday-api", "text": "Teste Sunday API"}],
            "T8 link (formato objeto)",
        )
    read_values(item, "T8 link: relê values")

    # TESTE 9 — people (usa apenas o usuário autenticado; nunca inventar user_id)
    people = mapping["responsavel"]
    if me_id:
        try_values(item, people["id"], [me_id, [me_id]], "T9 people")
        if people.get("is_system"):
            api("PATCH", f"/boards/items/{item}",
                {"assignee_user_ids": [me_id], "owner_user_id": me_id},
                note="T9 people: PATCH item (rota de coluna de sistema)")
        read_values(item, "T9 people: relê values")
        read_item(item, "T9 people: relê item")
    else:
        REPORT.append({"note": "T9 people: /auth/me sem id — teste não executado"})

    # TESTE 10 — board_relation (o mais importante)
    _, payload = api(
        "POST", f"/boards/{RELATION_BOARD_ID}/items", {"name": TARGET_ITEM_NAME},
        note="T10 cria item alvo no board 81",
    )
    target = str(payload["id"]) if isinstance(payload, dict) and payload.get("id") else ""
    if target:
        OWNED_ITEMS.add(target)
        relacao = mapping["relacao"]
        ok = try_values(
            item, relacao["id"],
            [target, [target], {"item_ids": [target]}, {"linked_item_ids": [target]}],
            "T10 relação",
        )
        if not ok and str(relacao_settings.get("source_board_id")) != RELATION_BOARD_ID:
            # Coluna aponta para o board errado; tenta corrigir a config (esperado 403).
            status, _ = api(
                "PATCH", f"/boards/columns/{relacao['id']}",
                {"settings": {"source_board_id": RELATION_BOARD_ID}},
                note="T10 relação: tenta reconfigurar coluna para board 81",
            )
            if 200 <= status < 300:
                try_values(
                    item, relacao["id"],
                    [target, [target], {"item_ids": [target]}],
                    "T10 relação (após reconfigurar)",
                )
        read_values(item, "T10 relação: relê values")
        read_item(item, "T10 relação: relê item")
    else:
        REPORT.append({"note": "T10: não criou item alvo no board 81 — relação não testada"})

    # Restaura o nome-marcador do item de teste (o T3 renomeou via coluna name)
    api("PATCH", f"/boards/items/{item}", {"name": ITEM_NAME},
        note="limpeza: restaura nome-marcador PODE EXCLUIR")

    out = "/tmp/sunday-values-retest-report.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(_sanitize(REPORT), handle, ensure_ascii=False, indent=2, default=str)
    print(f"\nRelatório: {out} ({len(REPORT)} passos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
