#!/usr/bin/env python3
"""Fase 0 — testes controlados de ESCRITA na API do Sunday (Testes 1-8 do roteiro).

Executa contra o sandbox autorizado e produz um relatório JSON + resumo legível.

Guard-rails (inegociáveis):
- Escrita permitida SOMENTE no board 80 ("SANDBOX - API SUNDAY - NÃO USAR") e no board
  "SANDBOX - API SUNDAY - RELATION" (criado por este script, uma única vez, no ws 22).
- Antes de qualquer escrita, o nome do board 80 é conferido; se divergir, aborta.
- Toda mutação em recurso filho (grupo/item/coluna/comentário/anexo/automação) só é
  permitida em recursos criados por este script (ids rastreados em OWNED).
- Dados 100% fictícios (prefixo "TESTE-FICTICIO"). Nenhum dado real é enviado.
- O token nunca é impresso; headers são redigidos no relatório.

Uso (requer SUNDAY_API_TOKEN e opcionalmente SUNDAY_API_URL no ambiente):

    python scripts/sunday_fase0_write_tests.py --out /tmp/sunday-write-report.json
    python scripts/sunday_fase0_write_tests.py --skip-webhook   # sem o Teste 8
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

DEFAULT_API = "https://sunday-api-757613635701.us-central1.run.app"
SANDBOX_BOARD_ID = "80"
SANDBOX_BOARD_NAME = "SANDBOX - API SUNDAY - NÃO USAR"
RELATION_BOARD_NAME = "SANDBOX - API SUNDAY - RELATION"
WORKSPACE_ID = "22"
FICT = "TESTE-FICTICIO"
WEBHOOK_SITE = "https://webhook.site"

REPORT: list[dict] = []
OWNED: dict[str, set[str]] = {
    "boards": {SANDBOX_BOARD_ID},
    "groups": set(),
    "items": set(),
    "columns": set(),
    "comments": set(),
    "attachments": set(),
    "automations": set(),
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
    return os.environ.get("SUNDAY_API_URL", DEFAULT_API).strip().rstrip("/") or DEFAULT_API


def _assert_write_allowed(method: str, path: str) -> None:
    """Bloqueia mutações fora dos sandboxes e de recursos criados pelo script."""
    if method == "GET":
        return
    parts = [p for p in path.split("?")[0].split("/") if p]
    if parts and parts[0] == "boards":
        if len(parts) == 1:  # POST /boards (criação do board RELATION)
            return
        second = parts[1]
        if second in OWNED["boards"]:
            return
        resource_map = {
            "groups": "groups",
            "items": "items",
            "columns": "columns",
            "comments": "comments",
            "attachments": "attachments",
        }
        if second in resource_map and len(parts) >= 3:
            if parts[2] in OWNED[resource_map[second]]:
                return
        raise GuardrailError(f"Escrita bloqueada pelo guard-rail: {method} {path}")
    if parts and parts[0] == "automations" and len(parts) >= 2:
        if parts[1] in OWNED["automations"]:
            return
        raise GuardrailError(f"Escrita bloqueada pelo guard-rail: {method} {path}")
    raise GuardrailError(f"Escrita bloqueada pelo guard-rail (rota não prevista): {method} {path}")


def api(
    method: str,
    path: str,
    body: dict | None = None,
    *,
    raw_body: bytes | None = None,
    content_type: str | None = None,
    note: str = "",
    timeout: int = 60,
) -> tuple[int, object]:
    """Chamada à API do Sunday com registro no relatório (token redigido)."""
    _assert_write_allowed(method, path)
    url = f"{_base()}{path}"
    data = raw_body
    headers = {"X-Sunday-Token": _token()}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    status, payload = 0, None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
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
    REPORT.append(
        {
            "note": note,
            "method": method,
            "path": path,
            "request_body": body
            if body is not None
            else (f"<binário {len(raw_body)}B>" if raw_body else None),
            "status": status,
            "response": payload,
        },
    )
    print(f"[{status}] {method} {path}  {note}")
    return status, payload


def _own(kind: str, payload: object) -> str | None:
    if isinstance(payload, dict) and payload.get("id") is not None:
        rid = str(payload["id"])
        OWNED[kind].add(rid)
        return rid
    return None


def preflight() -> None:
    status, me = api("GET", "/auth/me", note="identidade do token")
    if status != 200:
        print("ERRO: token inválido ou API indisponível.", file=sys.stderr)
        sys.exit(2)
    status, board = api("GET", f"/boards/{SANDBOX_BOARD_ID}", note="preflight sandbox")
    name = board.get("name") if isinstance(board, dict) else None
    if status != 200 or name != SANDBOX_BOARD_NAME:
        print(
            f"ABORTADO: board {SANDBOX_BOARD_ID} não é o sandbox esperado "
            f"(nome retornado: {name!r}).",
            file=sys.stderr,
        )
        sys.exit(2)


def teste1_crud() -> dict[str, str]:
    """CRUD básico: grupo, item, coluna text, value, comentário."""
    ids: dict[str, str] = {}
    _, groups = api("GET", f"/boards/{SANDBOX_BOARD_ID}/groups", note="T1 grupos antes")
    _, payload = api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/groups",
        {"name": f"{FICT} Grupo A", "color": "blue"},
        note="T1 cria grupo",
    )
    ids["group"] = _own("groups", payload) or ""
    api(
        "PATCH",
        f"/boards/groups/{ids['group']}",
        {"name": f"{FICT} Grupo A (editado)"},
        note="T1 altera grupo",
    )
    _, payload = api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/items",
        {"name": f"{FICT} Item 1", "group_id": ids["group"]},
        note="T1 cria item",
    )
    ids["item"] = _own("items", payload) or ""
    api("GET", f"/boards/{SANDBOX_BOARD_ID}/items", note="T1 lê itens")
    api(
        "PATCH",
        f"/boards/items/{ids['item']}",
        {"name": f"{FICT} Item 1 (editado)", "description": "Descrição fictícia."},
        note="T1 altera item",
    )
    api(
        "PATCH",
        f"/boards/items/{ids['item']}/status",
        {"status": "follow_up", "cascade": False},
        note="T1 altera status de sistema",
    )
    _, payload = api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/columns",
        {"label": f"{FICT} Texto", "type": "text"},
        note="T1 cria coluna text",
    )
    ids["column_text"] = _own("columns", payload) or ""
    api("GET", f"/boards/{SANDBOX_BOARD_ID}/columns", note="T1 lê colunas")
    api(
        "PATCH",
        f"/boards/items/{ids['item']}/values/{ids['column_text']}",
        {"value": "valor fictício v1"},
        note="T1 grava value",
    )
    api("GET", f"/boards/items/{ids['item']}/values", note="T1 lê values")
    api(
        "PATCH",
        f"/boards/items/{ids['item']}/values/{ids['column_text']}",
        {"value": "valor fictício v2"},
        note="T1 altera value",
    )
    _, payload = api(
        "POST",
        f"/boards/items/{ids['item']}/comments",
        {"body": f"{FICT} comentário 1", "kind": "reply"},
        note="T1 cria comentário",
    )
    ids["comment"] = _own("comments", payload) or ""
    api("GET", f"/boards/items/{ids['item']}/comments", note="T1 lê comentários")
    return ids


COLUMN_TYPE_CASES: list[tuple[str, dict, object, object]] = [
    ("text", {}, "texto fictício", "texto fictício 2"),
    ("long_text", {}, "parágrafo fictício\nlinha 2", "parágrafo alterado"),
    ("number", {}, 42, 43.5),
    (
        "status",
        {"options": [{"key": "opt_1", "label": "Aberto", "color": "sky"},
                     {"key": "opt_2", "label": "Fechado", "color": "green"}]},
        "opt_1",
        "opt_2",
    ),
    (
        "status_multi",
        {"options": [{"key": "opt_1", "label": "A", "color": "sky"},
                     {"key": "opt_2", "label": "B", "color": "pink"}]},
        ["opt_1"],
        ["opt_1", "opt_2"],
    ),
    (
        "dropdown",
        {"options": [{"key": "opt_1", "label": "Um", "color": "sky"},
                     {"key": "opt_2", "label": "Dois", "color": "sky"}]},
        "opt_1",
        "opt_2",
    ),
    ("date", {}, "2026-01-15", "2026-02-20"),
    ("checkbox", {}, True, False),
    ("people", {}, "@ME@", None),
    ("timeline", {}, {"start": "2026-01-01", "end": "2026-01-31"},
     {"start": "2026-02-01", "end": "2026-02-28"}),
    ("rating", {}, 3, 5),
    ("tags", {}, ["ficticio-a", "ficticio-b"], ["ficticio-c"]),
    ("link", {}, "https://example.com/ficticio", "https://example.org/ficticio2"),
    ("file_link", {}, "https://example.com/arquivo-ficticio.pdf", None),
    ("email", {}, "ficticio@example.com", "ficticio2@example.com"),
    ("phone", {}, "+55 11 90000-0000", "+55 11 91111-1111"),
    ("dependency", {}, "@ITEM2@", None),
    ("formula", {"expression": "1 + 1"}, None, None),
    ("time_tracking", {}, None, None),
    ("creation_log", {}, None, None),
]


def teste2_tipos(item_id: str, second_item_id: str, me_id: str) -> None:
    """Cria uma coluna de cada tipo e grava/lê/altera values fictícios."""
    for col_type, extra, v1, v2 in COLUMN_TYPE_CASES:
        payload_body = {"label": f"{FICT} {col_type}", "type": col_type, **extra}
        status, payload = api(
            "POST",
            f"/boards/{SANDBOX_BOARD_ID}/columns",
            payload_body,
            note=f"T2 cria coluna {col_type}",
        )
        col_id = _own("columns", payload)
        if status not in (200, 201) or not col_id:
            continue
        for tag, value in (("v1", v1), ("v2", v2)):
            if value is None:
                continue
            if value == "@ME@":
                value = me_id
            if value == "@ITEM2@":
                value = {"links": [{"item_id": second_item_id}]}
            api(
                "PATCH",
                f"/boards/items/{item_id}/values/{col_id}",
                {"value": value},
                note=f"T2 grava {col_type} {tag}",
            )
        api("GET", f"/boards/items/{item_id}/values", note=f"T2 relê values ({col_type})")


def teste3_relation(item_80: str) -> tuple[str, str, str]:
    """board_relation entre sandbox 80 e o board RELATION (criado aqui)."""
    _, boards = api("GET", "/boards", note="T3 boards visíveis (dedup do RELATION)")
    relation_board_id = ""
    if isinstance(boards, list):
        for board in boards:
            if isinstance(board, dict) and board.get("name") == RELATION_BOARD_NAME:
                relation_board_id = str(board["id"])
    if not relation_board_id:
        _, payload = api(
            "POST",
            "/boards",
            {
                "name": RELATION_BOARD_NAME,
                "description": "Sandbox de teste de board_relation. Pode apagar.",
                "template_key": "board",
                "workspace_id": WORKSPACE_ID,
            },
            note="T3 cria board RELATION",
        )
        relation_board_id = _own("boards", payload) or ""
    else:
        OWNED["boards"].add(relation_board_id)
    if not relation_board_id:
        return "", "", ""
    _, payload = api(
        "POST",
        f"/boards/{relation_board_id}/items",
        {"name": f"{FICT} Alvo da relação"},
        note="T3 cria item no RELATION",
    )
    target_item = _own("items", payload) or ""
    _, payload = api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/columns",
        {
            "label": f"{FICT} Conexão",
            "type": "board_relation",
            "source_board_id": relation_board_id,
        },
        note="T3 cria coluna board_relation",
    )
    relation_col = _own("columns", payload) or ""
    if relation_col and target_item:
        api(
            "PATCH",
            f"/boards/items/{item_80}/values/{relation_col}",
            {"value": {"links": [{"item_id": target_item}]}},
            note="T3 vincula itens",
        )
        api("GET", f"/boards/items/{item_80}/values", note="T3 relê values (reconstrução)")
        api(
            "GET",
            f"/boards/{SANDBOX_BOARD_ID}/columns",
            note="T3 relê colunas (settings da conexão)",
        )
    return relation_board_id, target_item, relation_col


def teste5_mirror(relation_board_id: str, item_80: str) -> None:
    if not relation_board_id:
        return
    _, cols = api("GET", f"/boards/{relation_board_id}/columns", note="T5 colunas do RELATION")
    source_col = ""
    if isinstance(cols, list):
        for col in cols:
            if isinstance(col, dict) and col.get("type") in ("text", "status"):
                source_col = str(col["id"])
                break
    if not source_col:
        return
    _, payload = api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/columns",
        {
            "label": f"{FICT} Espelho",
            "type": "mirror",
            "source_board_id": relation_board_id,
            "source_column_id": source_col,
        },
        note="T5 cria coluna mirror",
    )
    mirror_col = _own("columns", payload) or ""
    api("GET", f"/boards/items/{item_80}/values", note="T5 values com mirror")
    api(
        "GET",
        f"/boards/{SANDBOX_BOARD_ID}/mirror-values?column_id={mirror_col}",
        note="T5 mirror-values (esperado 403 p/ token)",
    )


def _tiny_pdf() -> bytes:
    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n")
    objects = [
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n",
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n",
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n",
    ]
    for obj in objects:
        buffer.write(obj)
    buffer.write(b"trailer<</Root 1 0 R>>\n%%EOF\n")
    return buffer.getvalue()


def teste_extra_subitens(parent_item: str) -> None:
    """hierarchy_depth do board + criação de subitem (parent_item_id)."""
    api(
        "PATCH",
        f"/boards/{SANDBOX_BOARD_ID}",
        {"hierarchy_depth": 2},
        note="TX habilita subitens (hierarchy_depth=2)",
    )
    _, payload = api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/items",
        {"name": f"{FICT} Subitem 1", "parent_item_id": parent_item},
        note="TX cria subitem",
    )
    _own("items", payload)
    api("GET", "/users/directory", note="TX diretório de usuários (mapeamento people)")


def teste6_anexos(item_id: str) -> None:
    pdf = _tiny_pdf()
    boundary = f"----SundayFase0{uuid.uuid4().hex}"
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        b'Content-Disposition: form-data; name="file"; filename="teste-ficticio.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n",
    )
    body.extend(pdf)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    status, payload = api(
        "POST",
        f"/boards/items/{item_id}/attachments/file",
        raw_body=bytes(body),
        content_type=f"multipart/form-data; boundary={boundary}",
        note=f"T6 upload PDF fictício ({len(pdf)} bytes)",
    )
    _own("attachments", payload)
    api(
        "POST",
        f"/boards/items/{item_id}/attachments/link",
        {"url": "https://example.com/anexo-ficticio", "filename": "link fictício"},
        note="T6 anexo por link",
    )
    api("GET", f"/boards/items/{item_id}/attachments", note="T6 lista anexos")


def teste7_comentarios(item_id: str, me_id: str) -> None:
    _, payload = api(
        "POST",
        f"/boards/items/{item_id}/comments",
        {"body": f"{FICT} com menção", "kind": "reply", "mention_user_ids": [me_id]},
        note="T7 comentário com menção",
    )
    comment_id = _own("comments", payload)
    if comment_id:
        api(
            "PATCH",
            f"/boards/comments/{comment_id}",
            {"body": f"{FICT} com menção (editado)"},
            note="T7 edita comentário",
        )
    _, payload = api(
        "POST",
        f"/boards/items/{item_id}/comments",
        {"body": f"{FICT} para excluir", "kind": "reply"},
        note="T7 comentário descartável",
    )
    disposable = _own("comments", payload)
    if disposable:
        api("DELETE", f"/boards/comments/{disposable}", note="T7 exclui comentário")
    api("GET", f"/boards/items/{item_id}/comments", note="T7 relê comentários")


def _webhook_site(method: str, path: str, body: dict | None = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{WEBHOOK_SITE}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def teste8_webhook() -> None:
    """Automação item_created→webhook com endpoint de eco (webhook.site)."""
    try:
        token_info = _webhook_site("POST", "/token", {"default_status": 200})
    except Exception as exc:  # noqa: BLE001 — rede externa opcional
        REPORT.append({"note": "T8 webhook.site indisponível", "error": str(exc)})
        print(f"T8 pulado: webhook.site indisponível ({exc})")
        return
    hook_id = token_info["uuid"]
    hook_url = f"{WEBHOOK_SITE}/{hook_id}"
    _, payload = api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/automations",
        {
            "title": f"{FICT} webhook",
            "enabled": True,
            "trigger": {"type": "item_created", "config": {}},
            "conditions": [],
            "actions": [{"type": "webhook", "config": {"url": hook_url}}],
        },
        note="T8 cria automação item_created→webhook",
    )
    automation_id = _own("automations", payload)
    api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/items",
        {"name": f"{FICT} dispara webhook OK"},
        note="T8 item para disparo (endpoint 200)",
    )
    deliveries: list[dict] = []
    for _ in range(18):
        time.sleep(10)
        result = _webhook_site("GET", f"/token/{hook_id}/requests?sorting=newest")
        deliveries = result.get("data", []) if isinstance(result, dict) else []
        if deliveries:
            break
    REPORT.append(
        {
            "note": "T8 entregas com endpoint 200",
            "count": len(deliveries),
            "deliveries": [
                {
                    "method": d.get("method"),
                    "headers": d.get("headers"),
                    "content": d.get("content"),
                    "created_at": d.get("created_at"),
                }
                for d in deliveries[:3]
            ],
        },
    )
    print(f"T8: {len(deliveries)} entrega(s) com endpoint 200")
    # Fase de erro: endpoint passa a responder 500 para observar retries.
    try:
        _webhook_site("PUT", f"/token/{hook_id}", {"default_status": 500})
    except Exception as exc:  # noqa: BLE001
        REPORT.append({"note": "T8 não conseguiu configurar 500", "error": str(exc)})
    api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/items",
        {"name": f"{FICT} dispara webhook ERRO"},
        note="T8 item para disparo (endpoint 500)",
    )
    time.sleep(180)
    result = _webhook_site("GET", f"/token/{hook_id}/requests?sorting=newest")
    error_phase = result.get("data", []) if isinstance(result, dict) else []
    REPORT.append(
        {
            "note": "T8 entregas na fase 500 (retries em ~3min)",
            "total_requests_no_endpoint": len(error_phase),
            "timestamps": [d.get("created_at") for d in error_phase[:10]],
        },
    )
    if automation_id:
        api("GET", f"/automations/{automation_id}/runs", note="T8 runs da automação")
        api(
            "PATCH",
            f"/automations/{automation_id}",
            {"enabled": False},
            note="T8 desativa automação (limpeza)",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/tmp/sunday-write-report.json")
    parser.add_argument("--skip-webhook", action="store_true")
    args = parser.parse_args()

    preflight()
    _, me = api("GET", "/auth/me", note="usuário para menções/people")
    me_id = str(me.get("id", "")) if isinstance(me, dict) else ""

    ids = teste1_crud()
    _, payload = api(
        "POST",
        f"/boards/{SANDBOX_BOARD_ID}/items",
        {"name": f"{FICT} Item 2 (dependência)"},
        note="item auxiliar p/ dependency",
    )
    second_item = _own("items", payload) or ""
    teste2_tipos(ids["item"], second_item, me_id)
    relation_board, _target, _col = teste3_relation(ids["item"])
    teste5_mirror(relation_board, ids["item"])
    teste_extra_subitens(ids["item"])
    teste6_anexos(ids["item"])
    teste7_comentarios(ids["item"], me_id)
    if not args.skip_webhook:
        teste8_webhook()

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(REPORT, handle, ensure_ascii=False, indent=2, default=str)
    print(f"\nRelatório completo: {args.out} ({len(REPORT)} passos)")
    failures = [
        step
        for step in REPORT
        if isinstance(step.get("status"), int) and step["status"] not in (200, 201, 204)
    ]
    print(f"Passos com status != 2xx: {len(failures)} (ver relatório; alguns são esperados)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
