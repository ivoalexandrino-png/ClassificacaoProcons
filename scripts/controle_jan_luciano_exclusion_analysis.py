#!/usr/bin/env python3
"""Cruzamento Jan/Luciano (Monday) × Autentique — o que excluir ou manter (somente leitura)."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from classificacao_procons.contratos.autentique.client import (  # noqa: E402
    AutentiqueClientError,
    list_documents,
)
from classificacao_procons.contratos.constants import (  # noqa: E402
    MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
)
from classificacao_procons.contratos.controle_dedup import normalize_controle_title  # noqa: E402
from classificacao_procons.contratos.controle_status import (  # noqa: E402
    resolve_controle_status_for_track,
)
from classificacao_procons.contratos.signer_identity import (  # noqa: E402
    find_jan_signer,
    find_luciano_signer,
)
from classificacao_procons.monday.client import _graphql_request, get_api_token_from_env  # noqa: E402

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
HEX_ID_RE = re.compile(r"\b[0-9a-f]{40,64}\b", re.IGNORECASE)
JAN_KEY = "contratos pendentes de assinatura jan"
LUCIANO_KEY = "contratos pendentes de assinatura luciano"


@dataclass
class MondayRow:
    name: str
    group_title: str
    track: str
    status: str | None
    tipo: str | None
    platform: str | None
    link_blob: str
    doc_ids: tuple[str, ...]


def _norm_group(title: str) -> str:
    n = unicodedata.normalize("NFKD", title.casefold())
    return "".join(c for c in n if not unicodedata.combining(c)).strip()


def _extract_doc_ids(*parts: str) -> tuple[str, ...]:
    found: set[str] = set()
    for text in parts:
        for match in UUID_RE.findall(text or ""):
            found.add(match.casefold())
        for match in HEX_ID_RE.findall(text or ""):
            if len(match) >= 40:
                found.add(match.casefold())
    return tuple(sorted(found))


def _platform_autentique(value: str | None) -> bool:
    return (value or "").strip().casefold() == "autentique"


def fetch_jan_luciano_monday(*, api_token: str) -> list[MondayRow]:
    rows: list[MondayRow] = []
    cursor: str | None = None
    for _ in range(100):
        data = _graphql_request(
            api_token=api_token,
            query="""
            query ($boardId: ID!, $limit: Int!, $cursor: String) {
              boards(ids: [$boardId]) {
                items_page(limit: $limit, cursor: $cursor) {
                  cursor
                  items {
                    id
                    name
                    group { title }
                    column_values { column { title } text value }
                  }
                }
              }
            }
            """,
            variables={
                "boardId": MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
                "limit": 100,
                "cursor": cursor,
            },
        )
        page = data["boards"][0]["items_page"]
        for item in page["items"]:
            group_title = str((item.get("group") or {}).get("title") or "")
            gkey = _norm_group(group_title)
            if gkey not in (JAN_KEY, LUCIANO_KEY):
                continue
            track = "luciano" if gkey == LUCIANO_KEY else "jan"
            cols = {c["column"]["title"]: c for c in item.get("column_values", [])}
            platform = (cols.get("Nome da Plataforma") or {}).get("text")
            status = (cols.get("Status") or {}).get("text")
            tipo = (cols.get("Tipo") or {}).get("text")
            link_col = cols.get("Link para assinatura") or {}
            link_blob = str(link_col.get("text") or "") + str(link_col.get("value") or "")
            name = str(item.get("name") or "")
            rows.append(
                MondayRow(
                    name=name,
                    group_title=group_title,
                    track=track,
                    status=status,
                    tipo=tipo,
                    platform=platform,
                    link_blob=link_blob,
                    doc_ids=_extract_doc_ids(link_blob, name),
                ),
            )
        cursor = page.get("cursor")
        if not cursor:
            break
    return rows


def _autentique_signer_state(document) -> dict[str, bool]:
    jan = find_jan_signer(document.signatures)
    luc = find_luciano_signer(document.signatures)
    return {
        "jan_signed": bool(jan and jan.signed_at),
        "luciano_signed": bool(luc and luc.signed_at),
        "fully_signed": document.is_fully_signed,
    }


def main() -> int:
    monday_token = get_api_token_from_env()
    if not monday_token:
        print("MONDAY_API_TOKEN ausente", file=sys.stderr)
        return 1
    try:
        documents = list_documents(max_pages=50)
    except AutentiqueClientError as exc:
        print(f"Autentique: {exc}", file=sys.stderr)
        return 1

    by_id = {d.document_id.casefold(): d for d in documents}
    by_norm_name: dict[str, list] = defaultdict(list)
    for doc in documents:
        by_norm_name[normalize_controle_title(doc.name)].append(doc)

    monday_rows = fetch_jan_luciano_monday(api_token=monday_token)

    excluir: list[dict] = []
    manter: list[dict] = []
    revisar: list[dict] = []

    for row in monday_rows:
        matched = None
        match_kind = None
        for doc_id in row.doc_ids:
            if doc_id in by_id:
                matched = by_id[doc_id]
                match_kind = "id"
                break
        if matched is None:
            candidates = by_norm_name.get(normalize_controle_title(row.name), [])
            if len(candidates) == 1:
                matched = candidates[0]
                match_kind = "titulo"
            elif len(candidates) > 1:
                fully = [c for c in candidates if c.is_fully_signed]
                if len(fully) == 1:
                    matched = fully[0]
                    match_kind = "titulo_ambiguo_assinado"

        if matched is None:
            revisar.append({
                "elemento_monday": row.name,
                "fila": row.track,
                "status_monday": row.status,
                "plataforma": row.platform,
                "motivo": "sem_match_autentique",
                "acao": "revisar_manualmente_ou_vincular_id",
            })
            continue

        state = _autentique_signer_state(matched)
        expected_status = resolve_controle_status_for_track(matched, track=row.track)

        if matched.is_fully_signed:
            excluir.append({
                "elemento_monday": row.name,
                "fila": row.track,
                "status_monday": row.status,
                "plataforma": row.platform,
                "documento_autentique": matched.name,
                "match": match_kind,
                "autentique_fully_signed": True,
                "motivo": "ja_assinado_por_todos_no_autentique_nao_deveria_ficar_em_pendentes",
                "acao": "excluir_ou_mover_para_assinados_se_unico_registro",
            })
            continue

        if row.status and row.status.casefold() == "assinado":
            excluir.append({
                "elemento_monday": row.name,
                "fila": row.track,
                "status_monday": row.status,
                "plataforma": row.platform,
                "documento_autentique": matched.name,
                "match": match_kind,
                "autentique_fully_signed": False,
                "motivo": "status_monday_assinado_mas_autentique_ainda_pendente",
                "acao": "revisar_status_monday_nao_excluir_sem_confirmar",
            })
            continue

        if row.status and expected_status and row.status.casefold() != expected_status.casefold():
            manter.append({
                "elemento_monday": row.name,
                "fila": row.track,
                "status_monday": row.status,
                "status_esperado": expected_status,
                "documento_autentique": matched.name,
                "match": match_kind,
                "motivo": "pendente_ok_mas_status_desalinhado",
                "acao": "sync_status_nao_excluir",
                **state,
            })
            continue

        manter.append({
            "elemento_monday": row.name,
            "fila": row.track,
            "status_monday": row.status,
            "documento_autentique": matched.name,
            "match": match_kind,
            "motivo": "pendente_coerente_com_autentique",
            "acao": "manter",
            **state,
        })

    # Duplicatas mesma fila + titulo (qualquer plataforma)
    buckets: dict[tuple[str, str, str], list[MondayRow]] = defaultdict(list)
    for row in monday_rows:
        buckets[(row.track, row.group_title, normalize_controle_title(row.name))].append(row)

    dup_excluir: list[dict] = []
    for (_track, _group, norm), group in buckets.items():
        if len(group) < 2:
            continue
        keeper_name = min(group, key=lambda r: (len(r.name), r.name)).name
        for row in group:
            if row.name == keeper_name:
                continue
            dup_excluir.append({
                "elemento_monday": row.name,
                "fila": row.track,
                "plataforma": row.platform,
                "motivo": "duplicata_mesma_fila_mesmo_titulo_normalizado",
                "acao": "excluir_se_sobra" if _platform_autentique(row.platform) else "excluir_preferencialmente_se_sobra",
                "manter_elemento": keeper_name,
            })

    report = {
        "autentique_documentos_feed": len(documents),
        "monday_jan_luciano_linhas": len(monday_rows),
        "excluir_ja_assinado_autentique": excluir,
        "duplicatas_mesma_fila": dup_excluir,
        "manter": manter,
        "revisar_sem_match": revisar,
        "resumo": {
            "excluir_assinado_autentique": len(excluir),
            "duplicatas_sugeridas": len(dup_excluir),
            "manter": len(manter),
            "revisar": len(revisar),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
