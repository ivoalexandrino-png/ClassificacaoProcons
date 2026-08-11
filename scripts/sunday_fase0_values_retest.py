#!/usr/bin/env python3
"""Fase 0 — reteste de VALUES e board_relation na API do Sunday (sandbox 80/81).

Escopo estrito deste reteste (NÃO repete a Fase 0 inteira):

- Confirma que as colunas "TESTE - *" existem no board 80 (configuradas
  manualmente) e detecta se são colunas novas (custom) ou colunas de sistema
  renomeadas (Nome/Status/Data/Responsável).
- Cria 1 item fictício no board 80.
- Grava e relê values de cada coluna usando o endpoint correto (values/ para
  colunas custom; PATCH /boards/items/:id ou /:id/status para colunas de
  sistema, conforme já confirmado em testes anteriores).
- board_relation: só escreve se a coluna estiver configurada para o board 81
  (sandbox autorizado). Se estiver apontando para outro board, ABORTA esse
  subteste especificamente (não escreve em nenhum outro board) e reporta o
  achado — sem travar o restante da bateria de testes.
- NÃO cria, altera nem apaga colunas, grupos ou boards.
- NÃO escreve em nenhum board além de 80 e 81.

Uso (requer SUNDAY_API_TOKEN e SUNDAY_API_URL no ambiente):

    python scripts/sunday_fase0_values_retest.py --out /tmp/sunday-values-retest.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

SANDBOX_BOARD_ID = "80"
SANDBOX_BOARD_NAME = "SANDBOX - API SUNDAY - NÃO USAR"
RELATION_BOARD_ID = "81"
RELATION_BOARD_NAME = "SANDBOX - API SUNDAY - RELATION"
WORKSPACE_ID = "22"

# título (normalizado para minúsculas) -> chave interna usada no relatório
REQUIRED_COLUMNS = {
    "teste - texto": "texto",
    "teste - número": "numero",
    "teste - status": "status",
    "teste - data": "data",
    "teste - responsável": "responsavel",
    "teste - link": "link",
    "teste - checkbox": "checkbox",
    "teste - relação": "relacao",
}

SENSITIVE_FIELD_NAMES = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "x-sunday-token",
}
PRIVATE_FIELD_NAMES = {
    "approver_user_ids",
    "assignee_user_ids",
    "author_name",
    "author_user_id",
    "calendar_event_organizer_email",
    "created_by",
    "creator_user_id",
    "email",
    "linked_user_id",
    "manager_user_id",
    "members",
    "mention_user_ids",
    "owner_user_id",
    "team_ids",
    "uploader_user_id",
    "avatar_url",
    "hire_date",
    "job_title",
    "last_login_at",
    "updated_by_user",
}
PRIVATE_RESPONSE_NOTES = {
    "T9 auth/me para people",
}

REPORT: list[dict] = []
OWNED: dict[str, set[str]] = {
    "boards": {SANDBOX_BOARD_ID, RELATION_BOARD_ID},
    "items": set(),
}


class GuardrailError(RuntimeError):
    pass


def _token() -> str:
    token = os.environ.get("SUNDAY_API_TOKEN", "").strip()
    if not token:
        print("ERRO: SUNDAY_API_TOKEN ausente no ambiente.", file=sys.stderr)
        sys.exit(2)
    return token


def _base() -> str:
    base = os.environ.get("SUNDAY_API_URL", "").strip().rstrip("/")
    if not base:
        print("ERRO: SUNDAY_API_URL ausente no ambiente.", file=sys.stderr)
        sys.exit(2)
    return base


def _sanitize(value: object) -> object:
    token = os.environ.get("SUNDAY_API_TOKEN", "")
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            lower_key = str(key).lower()
            if lower_key in SENSITIVE_FIELD_NAMES:
                continue
            if lower_key in PRIVATE_FIELD_NAMES:
                out[key] = "<omitido: dados de identidade>"
                continue
            out[key] = _sanitize(item)
        return out
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and token and token in value:
        return value.replace(token, "[REDACTED]")
    return value


def _record(entry: dict) -> None:
    safe_entry = dict(entry)
    if safe_entry.get("note") in PRIVATE_RESPONSE_NOTES:
        safe_entry["response"] = "<omitido: dados de identidade>"
    REPORT.append(_sanitize(safe_entry))


def _own_item(payload: object, allowed_boards: set[str]) -> None:
    if isinstance(payload, dict) and "id" in payload:
        board_id = str(payload.get("board_id", ""))
        if board_id not in allowed_boards:
            raise GuardrailError(f"item criado em board fora do sandbox autorizado: {board_id}")
        OWNED["items"].add(str(payload["id"]))


def api(
    method: str, path: str, body: dict | list | None = None, note: str = ""
) -> tuple[int, object]:
    url = f"{_base()}{path}"
    headers = {"X-Sunday-Token": _token()}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    status, text = 0, ""
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            text = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        text = exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        status, text = -1, str(exc.reason)
    try:
        payload = json.loads(text) if text else None
    except json.JSONDecodeError:
        payload = text[:400]
    _record(
        {
            "note": note,
            "method": method,
            "path": path,
            "request_body": body,
            "status": status,
            "response": payload,
        }
    )
    return status, payload


def guard_board_name(board_id: str, expected_name: str) -> None:
    status, payload = api("GET", f"/boards/{board_id}", note=f"preflight board {board_id}")
    if status != 200 or not isinstance(payload, dict):
        raise GuardrailError(f"não foi possível confirmar o board {board_id} (status {status})")
    if payload.get("name") != expected_name:
        raise GuardrailError(
            f"board {board_id} tem nome inesperado: {payload.get('name')!r} "
            f"(esperado {expected_name!r}) — abortando por segurança"
        )


def teste1_discover_columns() -> tuple[dict[str, dict], list]:
    status, payload = api("GET", f"/boards/{SANDBOX_BOARD_ID}/columns", note="T1 colunas board 80")
    if status != 200 or not isinstance(payload, list):
        raise GuardrailError(f"falha ao ler colunas do board 80 (status {status})")

    status_b, board_payload = api(
        "GET", f"/boards/{SANDBOX_BOARD_ID}", note="T1 board 80 (status_set)"
    )
    status_set = board_payload.get("status_set", []) if isinstance(board_payload, dict) else []

    api("GET", f"/boards/{RELATION_BOARD_ID}/columns", note="T1 colunas board 81 (contexto)")

    found: dict[str, dict] = {}
    for col in payload:
        label = (col.get("label") or "").strip().lower()
        if label in REQUIRED_COLUMNS:
            key = REQUIRED_COLUMNS[label]
            found[key] = col

    missing = [title for title, key in REQUIRED_COLUMNS.items() if key not in found]
    if missing:
        _record(
            {"note": "T1 colunas faltantes (nenhuma coluna com este título)", "missing": missing}
        )
        print("PAROU: colunas faltantes no board 80 (nenhum título correspondente encontrado):")
        for title in missing:
            print(f"  - {title}")
        with open("/tmp/sunday-values-retest.json", "w", encoding="utf-8") as fh:
            json.dump(REPORT, fh, ensure_ascii=False, indent=2)
        sys.exit(3)

    _record(
        {
            "note": "T1 mapa titulo->column_id/type/is_system/settings",
            "map": {
                key: {
                    "label": col.get("label"),
                    "column_id": col.get("id"),
                    "key": col.get("key"),
                    "type": col.get("type"),
                    "is_system": col.get("is_system"),
                    "settings": col.get("settings"),
                }
                for key, col in found.items()
            },
        }
    )
    return found, status_set


def teste2_item_ficticio() -> str:
    status, payload = api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/items",
        {"name": "TESTE VALUES API - PODE EXCLUIR"},
        note="T2 cria item ficticio board 80",
    )
    if status != 201 or not isinstance(payload, dict):
        raise GuardrailError(f"falha ao criar item de teste (status {status})")
    _own_item(payload, {SANDBOX_BOARD_ID})
    return str(payload["id"])


def custom_value_roundtrip(item_id: str, column: dict, value, note_prefix: str) -> None:
    col_id = column["id"]
    api(
        "PATCH",
        f"/boards/items/{item_id}/values/{col_id}",
        {"value": value},
        note=f"{note_prefix} grava value (custom column)",
    )
    api(
        "GET", f"/boards/items/{item_id}/values", note=f"{note_prefix} lê todos os values do item"
    )
    api(
        "GET",
        f"/boards/items/{item_id}/values/{col_id}",
        note=f"{note_prefix} lê value especifico (rota alternativa)",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/tmp/sunday-values-retest.json")
    args = parser.parse_args()

    try:
        guard_board_name(SANDBOX_BOARD_ID, SANDBOX_BOARD_NAME)
        guard_board_name(RELATION_BOARD_ID, RELATION_BOARD_NAME)

        columns, status_set = teste1_discover_columns()
        item_id = teste2_item_ficticio()

        # --- Teste 3: Texto ---
        texto_col = columns["texto"]
        if texto_col.get("is_system") and texto_col.get("key") == "name":
            _record(
                {
                    "note": (
                        "T3 texto é a coluna de sistema 'name' (nome do item), "
                        "não uma coluna de texto dedicada"
                    )
                }
            )
            api(
                "PATCH",
                f"/boards/items/{item_id}",
                {"name": "Teste Sunday API"},
                note="T3 texto grava via PATCH /boards/items/:id (system 'name')",
            )
        else:
            custom_value_roundtrip(item_id, texto_col, "Teste Sunday API", "T3 texto")

        # --- Teste 4: Número ---
        numero_col = columns["numero"]
        custom_value_roundtrip(item_id, numero_col, 12345, "T4 numero")

        # --- Teste 5: Status ---
        status_col = columns["status"]
        if status_col.get("is_system") and status_col.get("key") == "status":
            _record(
                {
                    "note": (
                        "T5 status é a coluna de sistema 'status', "
                        "opções vêm de board.status_set"
                    ),
                    "status_set": status_set,
                }
            )
            if status_set:
                chosen = status_set[0]["key"]
                api(
                    "PATCH",
                    f"/boards/items/{item_id}/status",
                    {"status": chosen, "cascade": False},
                    note=f"T5 status grava via PATCH /boards/items/:id/status (key={chosen})",
                )
        else:
            options = (status_col.get("settings") or {}).get("options") or []
            _record({"note": "T5 opções da coluna status custom", "options": options})
            if options:
                custom_value_roundtrip(item_id, status_col, options[0].get("key"), "T5 status")

        # --- Teste 6: Data ---
        data_col = columns["data"]
        if data_col.get("is_system") and data_col.get("key") == "target_date":
            _record({"note": "T6 data é a coluna de sistema 'target_date'"})
            api(
                "PATCH",
                f"/boards/items/{item_id}",
                {"target_date": "2026-01-15"},
                note="T6 data grava via PATCH /boards/items/:id (system 'target_date')",
            )
        else:
            custom_value_roundtrip(item_id, data_col, "2026-01-15", "T6 data")

        # --- Teste 7: Checkbox ---
        checkbox_col = columns["checkbox"]
        custom_value_roundtrip(item_id, checkbox_col, True, "T7 checkbox true")
        custom_value_roundtrip(item_id, checkbox_col, False, "T7 checkbox false")

        # --- Teste 8: Link ---
        link_col = columns["link"]
        custom_value_roundtrip(item_id, link_col, "https://example.com/teste-sunday-api", "T8 link")
        # tenta também o formato objeto (comum em colunas link tipo monday: {url, text})
        custom_value_roundtrip(
            item_id,
            link_col,
            {"url": "https://example.com/teste-sunday-api-obj", "text": "teste"},
            "T8b link (formato objeto)",
        )

        # --- Teste 9: People ---
        responsavel_col = columns["responsavel"]
        status_me, me_payload = api("GET", "/auth/me", note="T9 auth/me para people")
        user_id = None
        if status_me == 200 and isinstance(me_payload, dict):
            user_id = me_payload.get("id") or me_payload.get("user_id")
        if user_id:
            if responsavel_col.get("is_system") and responsavel_col.get("key") == "owner":
                _record({"note": "T9 responsavel é a coluna de sistema 'owner'"})
                api(
                    "PATCH",
                    f"/boards/items/{item_id}",
                    {"owner_user_id": user_id},
                    note="T9 people grava via PATCH /boards/items/:id (system 'owner_user_id')",
                )
            else:
                custom_value_roundtrip(item_id, responsavel_col, user_id, "T9 people")
        else:
            _record(
                {"note": "T9 sem user_id obtido de /auth/me — teste pulado, não inventamos user_id"}
            )

        # --- Teste 10: board_relation (o mais importante) ---
        relacao_col = columns["relacao"]
        relation_source_board = (relacao_col.get("settings") or {}).get("source_board_id")
        _record(
            {
                "note": "T10 verificacao de seguranca antes de escrever",
                "coluna_relacao_settings": relacao_col.get("settings"),
                "esperado_source_board_id": RELATION_BOARD_ID,
                "encontrado_source_board_id": relation_source_board,
            }
        )
        if str(relation_source_board) != RELATION_BOARD_ID:
            print(
                "PAROU o Teste 10 (board_relation): a coluna 'TESTE - Relação' está "
                f"configurada com source_board_id={relation_source_board!r}, e não "
                f"{RELATION_BOARD_ID!r} (board sandbox RELATION) como exigido. Para não "
                "arriscar escrita em outro board (guardrail: 'Nenhum outro board pode "
                "sofrer escrita'), este subteste foi abortado sem qualquer escrita na "
                "coluna. Corrija a configuração manual da coluna para apontar para o "
                "board 81 e reexecute apenas este teste."
            )
            _record(
                {
                    "note": (
                        "T10 ABORTADO por seguranca — "
                        "nenhuma escrita feita na coluna board_relation"
                    )
                }
            )
        else:
            status_t, target_payload = api(
                "POST",
                f"/boards/{RELATION_BOARD_ID}/items",
                {"name": "TESTE TARGET RELATION - PODE EXCLUIR"},
                note="T10 cria item alvo board 81",
            )
            if status_t == 201 and isinstance(target_payload, dict):
                _own_item(target_payload, {RELATION_BOARD_ID})
                target_item_id = str(target_payload["id"])
                for attempt_note, attempt_value in (
                    ("T10a valor=lista de ids", [target_item_id]),
                    ("T10b valor=id unico", target_item_id),
                    ("T10c valor=objeto item_ids", {"item_ids": [target_item_id]}),
                ):
                    custom_value_roundtrip(item_id, relacao_col, attempt_value, attempt_note)
                api(
                    "POST",
                    f"/boards/{SANDBOX_BOARD_ID}/links",
                    {
                        "source_item_id": item_id,
                        "target_board_id": RELATION_BOARD_ID,
                        "target_item_id": target_item_id,
                        "column_id": relacao_col["id"],
                    },
                    note=(
                        "T10 tenta endpoint dedicado /links "
                        "(esperado 403 conforme achados anteriores)"
                    ),
                )
            else:
                _record({"note": "T10 falha ao criar item alvo no board 81 — relation não testada"})

        # --- Teste 11 (extra, essencial p/ decisao GO/NO-GO): comentarios ---
        api(
            "POST",
            f"/boards/items/{item_id}/comments",
            {"body": "TESTE VALUES API - comentario ficticio", "kind": "reply"},
            note="T11 cria comentario ficticio",
        )
        api("GET", f"/boards/items/{item_id}/comments", note="T11 lê comentarios")

        api("GET", f"/boards/items/{item_id}/values", note="FINAL values do item de teste board 80")

        # a listagem completa do board traz dezenas de itens de rodadas anteriores;
        # não gravamos a listagem inteira no relatório, só o item de teste desta rodada
        # (que tem o shape "completo": inclui owner_user_id/creator_user_id/assignee_user_ids,
        # ausentes na resposta "slim" do PATCH).
        status_list, all_items = api(
            "GET", f"/boards/{SANDBOX_BOARD_ID}/items", note="__internal_do_not_keep__"
        )
        REPORT.pop()  # remove a listagem completa do relatório persistido
        final_item = None
        if status_list == 200 and isinstance(all_items, list):
            for it in all_items:
                if str(it.get("id")) == item_id:
                    final_item = it
                    break
        _record(
            {
                "note": (
                    "FINAL item de teste (shape completo, via listagem, "
                    "filtrado só o item desta rodada)"
                ),
                "item": final_item,
            }
        )

    except GuardrailError as exc:
        _record({"note": "GUARDRAIL ABORTOU O TESTE", "error": str(exc)})
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(REPORT, fh, ensure_ascii=False, indent=2)
        print(f"GUARDRAIL: {exc}", file=sys.stderr)
        return 4

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(REPORT, fh, ensure_ascii=False, indent=2)
    print(f"Relatório escrito em {args.out} ({len(REPORT)} entradas).")
    print(f"Item de teste criado no board 80: {item_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
