"""Auditoria caso a caso: filas Jan/Luciano no Controle × Autentique (somente leitura)."""

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
    AutentiqueDocumentSummary,
    list_documents,
)
from classificacao_procons.contratos.constants import (
    MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,  # noqa: E402
)
from classificacao_procons.contratos.controle_dedup import normalize_controle_title  # noqa: E402
from classificacao_procons.contratos.controle_status import (  # noqa: E402
    resolve_controle_status_for_track,
)
from classificacao_procons.contratos.signer_identity import (  # noqa: E402
    find_jan_signer,
    find_luciano_signer,
)
from classificacao_procons.monday.client import (  # noqa: E402
    _graphql_request,
    get_api_token_from_env,
)

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)

JAN_GROUP_KEY = "contratos pendentes de assinatura jan"
LUCIANO_GROUP_KEY = "contratos pendentes de assinatura luciano"


@dataclass
class TrackRow:
    item_id: str
    name: str
    group_title: str
    status: str | None
    tipo: str | None
    autentique_ids: tuple[str, ...]
    link_excerpt: str | None


def _normalize_group(title: str) -> str:
    n = unicodedata.normalize("NFKD", title.casefold())
    return "".join(c for c in n if not unicodedata.combining(c)).strip()


def _extract_ids(*texts: str) -> tuple[str, ...]:
    found: set[str] = set()
    for text in texts:
        for match in UUID_RE.findall(text or ""):
            found.add(match.casefold())
    return tuple(sorted(found))


def fetch_jan_luciano_rows(*, api_token: str) -> list[TrackRow]:
    rows: list[TrackRow] = []
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
                    column_values {
                      id
                      text
                      value
                      column { title }
                    }
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
            group = item.get("group") or {}
            group_title = str(group.get("title") or "")
            gkey = _normalize_group(group_title)
            if gkey not in (JAN_GROUP_KEY, LUCIANO_GROUP_KEY):
                continue
            cols = {
                str((c.get("column") or {}).get("title") or c.get("id")): str(c.get("text") or "")
                for c in item.get("column_values", [])
            }
            link = cols.get("Link para assinatura") or cols.get("long_text_mkvnwp6d") or ""
            blob = " ".join(cols.values()) + " " + link
            rows.append(
                TrackRow(
                    item_id=str(item["id"]),
                    name=str(item.get("name", "")),
                    group_title=group_title,
                    status=cols.get("Status"),
                    tipo=cols.get("Tipo"),
                    autentique_ids=_extract_ids(blob, str(item.get("name", ""))),
                    link_excerpt=(link[:120] + "…") if len(link) > 120 else link or None,
                ),
            )
        cursor = page.get("cursor")
        if not cursor:
            break
    return rows


def _track_from_group(group_title: str) -> str:
    return "luciano" if "luciano" in _normalize_group(group_title) else "jan"


def _signer_state(document: AutentiqueDocumentSummary) -> dict[str, object]:
    jan = find_jan_signer(document.signatures)
    luc = find_luciano_signer(document.signatures)
    return {
        "jan_signed": bool(jan and jan.signed_at),
        "luciano_signed": bool(luc and luc.signed_at),
        "fully_signed": document.is_fully_signed,
        "jan_pending": bool(jan and not jan.signed_at),
        "luciano_pending": bool(luc and not luc.signed_at),
    }


def _classify_case(
    *,
    jan_row: TrackRow | None,
    luc_row: TrackRow | None,
    document: AutentiqueDocumentSummary | None,
    doc_id: str | None,
) -> str:
    if document and document.is_fully_signed:
        return "excluir_autentique_100_assinado"
    if jan_row is None or luc_row is None:
        return "par_incompleto_jan_ou_luciano"
    ids_jan = set(jan_row.autentique_ids)
    ids_luc = set(luc_row.autentique_ids)
    if doc_id and ids_jan and ids_luc and ids_jan != ids_luc:
        return "ids_diferentes_entre_filas"
    if not ids_jan and not ids_luc:
        return "sem_autentique_id"
    if document is None:
        return "autentique_id_fora_do_feed"
    issues: list[str] = []
    for row, track in ((jan_row, "jan"), (luc_row, "luciano")):
        expected = resolve_controle_status_for_track(document, track=track)
        if (row.status or "").casefold().strip() != expected.casefold().strip():
            issues.append(f"status_{track}")
    if issues:
        return "status_desalinhado_" + "_".join(issues)
    return "alinhado"


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

    docs_by_id = {d.document_id.casefold(): d for d in documents}
    rows = fetch_jan_luciano_rows(api_token=monday_token)

    by_norm: dict[str, list[TrackRow]] = defaultdict(list)
    for row in rows:
        by_norm[normalize_controle_title(row.name)].append(row)

    # Pair by normalized title within Jan/Luciano groups only
    cases: list[dict] = []
    seen_pairs: set[str] = set()

    for norm_title, group_rows in sorted(by_norm.items(), key=lambda x: x[0]):
        jan_rows = [r for r in group_rows if _track_from_group(r.group_title) == "jan"]
        luc_rows = [r for r in group_rows if _track_from_group(r.group_title) == "luciano"]
        if len(jan_rows) > 1 or len(luc_rows) > 1:
            cases.append(
                {
                    "case_id": f"dup:{norm_title[:40]}",
                    "verdict": "duplicata_na_mesma_fila",
                    "normalized_title": norm_title,
                    "jan_items": [asdict(r) for r in jan_rows],
                    "luciano_items": [asdict(r) for r in luc_rows],
                    "action_before_sync": "revisar_arquivar_duplicatas_manualmente",
                },
            )
            continue

        jan_row = jan_rows[0] if jan_rows else None
        luc_row = luc_rows[0] if luc_rows else None
        pair_key = norm_title or (jan_row.item_id if jan_row else luc_row.item_id)  # type: ignore[union-attr]
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        all_ids = set()
        if jan_row:
            all_ids.update(jan_row.autentique_ids)
        if luc_row:
            all_ids.update(luc_row.autentique_ids)
        doc_id = next(iter(all_ids), None)
        document = docs_by_id.get(doc_id) if doc_id else None

        verdict = _classify_case(
            jan_row=jan_row,
            luc_row=luc_row,
            document=document,
            doc_id=doc_id,
        )

        autentique = None
        if document:
            autentique = {
                "document_id": document.document_id,
                "name": document.name,
                **_signer_state(document),
                "expected_status_jan": resolve_controle_status_for_track(document, track="jan"),
                "expected_status_luciano": resolve_controle_status_for_track(
                    document,
                    track="luciano",
                ),
            }

        action = "nenhuma_ate_revisar"
        if verdict == "alinhado":
            action = "ok_manter"
        elif verdict == "excluir_autentique_100_assinado":
            action = "fora_escopo_mover_ou_reconciliar_assinados"
        elif verdict == "sem_autentique_id":
            action = "vincular_id_ou_alinhar_titulo_antes_de_criar"
        elif verdict.startswith("status_desalinhado"):
            action = "somente_reconcile_status_sem_criar"
        elif verdict == "par_incompleto_jan_ou_luciano":
            action = "reparo_fila_faltante_quando_politica_permitir"
        elif verdict == "autentique_id_fora_do_feed":
            action = "validar_id_ou_documento_arquivado_no_autentique"

        cases.append(
            {
                "case_id": doc_id or f"title:{norm_title[:36]}",
                "normalized_title": norm_title,
                "verdict": verdict,
                "action_before_sync": action,
                "jan": asdict(jan_row) if jan_row else None,
                "luciano": asdict(luc_row) if luc_row else None,
                "autentique": autentique,
            },
        )

    by_verdict: dict[str, int] = defaultdict(int)
    for c in cases:
        by_verdict[c["verdict"]] += 1

    actionable = [
        c
        for c in cases
        if c["verdict"] not in ("excluir_autentique_100_assinado", "alinhado")
    ]

    report = {
        "scope": "Somente grupos Contratos Pendentes Jan e Luciano (demais grupos ignorados)",
        "autentique_documents_in_feed": len(documents),
        "monday_rows_jan_luciano_groups": len(rows),
        "cases_paired_by_title": len(cases),
        "counts_by_verdict": dict(sorted(by_verdict.items())),
        "actionable_cases_count": len(actionable),
        "actionable_cases": actionable,
        "aligned_cases_count": by_verdict.get("alinhado", 0),
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
