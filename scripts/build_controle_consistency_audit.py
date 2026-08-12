"""Etapa 2.1: auditoria de consistência e remediation_plan_v2 (sem mutations)."""

from __future__ import annotations

import json
import re
import sys
import uuid
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.controle_autentique_link import (
    autentique_ids_in_controle_link,
)
from classificacao_procons.contratos.controle_dedup import (
    normalize_controle_title,
    normalized_controle_titles_equal,
)
from classificacao_procons.contratos.controle_reconcile import find_duplicate_normalized_names
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import (
    build_controle_assinaturas_index,
    infer_controle_signer_track,
)
from classificacao_procons.monday.client import get_api_token_from_env

_HR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bferias\b|\bférias\b", re.I),
    re.compile(r"\brescis", re.I),
    re.compile(r"\bdeclarac", re.I),
    re.compile(r"\badmiss", re.I),
    re.compile(r"\btce\b", re.I),
    re.compile(r"\bplano\b.*\bsaude\b|\bplano\b.*\bsaúde\b", re.I),
    re.compile(r"\binclusao\b.*\bplano\b|\binclusão\b.*\bplano\b", re.I),
    re.compile(r"\bcodigo\b.*\bconduta\b|\bcódigo\b.*\bconduta\b", re.I),
    re.compile(r"\bficha\b.*\bregistro\b", re.I),
    re.compile(r"\bcarta\b.*\binclus", re.I),
    re.compile(r"\bacordo\b.*\bbanco\b.*\bhoras\b", re.I),
)

_PEDIDO = re.compile(r"\bpedido\b", re.I)
_B2B_INDICATORS = re.compile(
    r"\bb2b\b|\bfornec|\bcomercial\b|\bparceria\b|\bbonific|\breposic|\bmlm\b|"
    r"performance|brass\s*hill|conforto|nobilis|stick\s*rio|glam\s",
    re.I,
)
_HR_NEG = re.compile(
    r"\bferias\b|\bférias\b|\brescis|\badmiss|\btce\b|\bcolaborador\b|\brh\b|"
    r"\bplano\b.*\bsaude\b|\bfuncionario\b|\bfuncionário\b",
    re.I,
)
_OPER_NEG = re.compile(r"\bvaga\b.*\bgaragem\b|\bconstituic", re.I)
_CESSAO = re.compile(r"\bcessao\b|\bcessão\b", re.I)
_PARCERIA = re.compile(r"\bparceria\b|\btermo de parceria\b", re.I)
_RH_MENSAL = re.compile(r"\bcontrato\b.*\bmensal\b|\btermo de adesão\b", re.I)


def _doc_from_row(row: dict) -> AutentiqueDocumentSummary:
    sigs = tuple(
        AutentiqueSigner(
            public_id=s["public_id"],
            name=s.get("name"),
            email=s.get("email"),
            short_link=None,
            signed_at=s.get("signed_at"),
        )
        for s in row.get("signers") or []
    )
    status = row.get("document_status") or "pending"
    return AutentiqueDocumentSummary(
        document_id=row["autentique_document_id"],
        name=row["document_name"],
        created_at=None,
        signed_pdf_url="x" if status in {"fully_signed", "signed_pdf_present"} else None,
        signatures=sigs,
    )


def _item_doc_ids_in_index(item: ControleAssinaturasItem, index) -> set[str]:
    return {
        doc_id for doc_id, indexed in index.items_by_document_id if indexed.item_id == item.item_id
    }


def _compare_without_link(item: ControleAssinaturasItem, index) -> bool:
    return not _item_doc_ids_in_index(item, index)


def _has_explicit_autentique_id_line(link: str | None) -> bool:
    return "autentique id:" in (link or "").casefold()


def _hr_title_patterns(title: str) -> list[str]:
    n = normalize_controle_title(title)
    return [p.pattern for p in _HR_PATTERNS if p.search(n)]


def _archive_evidence(
    item: ControleAssinaturasItem,
    index,
    *,
    etapa2_reason: str | None = None,
) -> dict:
    link = item.signature_link or ""
    ids_index = _item_doc_ids_in_index(item, index)
    ids_link = autentique_ids_in_controle_link(link)
    hr_hits = _hr_title_patterns(item.name)
    tipo = (item.tipo or "").casefold()
    tipo_rh = any(
        token in tipo
        for token in (
            "rh",
            "ferias",
            "férias",
            "rescis",
            "admiss",
            "tce",
            "plano",
            "saude",
            "saúde",
        )
    )

    if ids_index:
        return {
            "evidence_type": "autentique_id_confirmed",
            "evidence": f"indexado por ID(s): {sorted(ids_index)}",
            "classification_reason": "item com Autentique ID no índice",
            "confidence": "high",
            "executable_archive": False,
            "plan_classification_v2": "MANUAL_REVIEW",
        }
    if ids_link and _has_explicit_autentique_id_line(link):
        return {
            "evidence_type": "autentique_id_confirmed",
            "evidence": f"linha Autentique ID: {ids_link}",
            "classification_reason": "ID explícito no link sem indexação completa",
            "confidence": "medium",
            "executable_archive": False,
            "plan_classification_v2": "MANUAL_REVIEW",
        }
    if tipo_rh and etapa2_reason == "hr_non_contract_title":
        return {
            "evidence_type": "metadata_confirmed",
            "evidence": f"tipo Monday={item.tipo!r}; etapa2={etapa2_reason}",
            "classification_reason": "metadado tipo + classificação etapa2 RH",
            "confidence": "medium",
            "executable_archive": False,
            "plan_classification_v2": "PROBABLE_ARCHIVE_REVIEW",
        }
    if "assina.ae" in link.casefold() or "autentique" in link.casefold():
        plan = "PROBABLE_ARCHIVE_REVIEW" if hr_hits else "MANUAL_REVIEW"
        return {
            "evidence_type": "autentique_url_confirmed",
            "evidence": link[:200],
            "classification_reason": "URL Autentique no link",
            "confidence": "medium",
            "executable_archive": False,
            "plan_classification_v2": plan,
        }
    if hr_hits:
        return {
            "evidence_type": "title_pattern_only",
            "evidence": "; ".join(hr_hits[:3]),
            "classification_reason": "padrão RH no título (sem ID Autentique)",
            "confidence": "low",
            "executable_archive": False,
            "plan_classification_v2": "PROBABLE_ARCHIVE_REVIEW",
        }
    if etapa2_reason == "hr_non_contract_title":
        return {
            "evidence_type": "group_context",
            "evidence": f"group_id={item.group_id}; etapa2={etapa2_reason}",
            "classification_reason": (
                "classificado RH na etapa2 sem padrão de título detectado agora"
            ),
            "confidence": "low",
            "executable_archive": False,
            "plan_classification_v2": "MANUAL_REVIEW",
        }
    return {
        "evidence_type": "other",
        "evidence": "sem evidência archive",
        "classification_reason": "não classificado para archive",
        "confidence": "low",
        "executable_archive": False,
        "plan_classification_v2": "MANUAL_REVIEW",
    }


def _classify_duplicate_group(
    normalized: str,
    entries: tuple[tuple[str, str], ...],
    index,
) -> tuple[str, list[dict]]:
    item_by_id = {i.item_id: i for i in index.all_items}
    rows: list[dict] = []
    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for item_id, name in entries:
        item = item_by_id.get(item_id)
        if item is None:
            continue
        track = infer_controle_signer_track(item)
        ids = autentique_ids_in_controle_link(item.signature_link or "")
        primary_id = ids[0] if ids else ""
        if not primary_id:
            for doc_id, indexed in index.items_by_document_id:
                if indexed.item_id == item_id:
                    primary_id = doc_id
                    break
        key = (primary_id.casefold(), track)
        row = {
            "monday_item_id": item_id,
            "title": name,
            "autentique_id": primary_id or None,
            "track_inferred": track,
            "group_id": item.group_id,
            "status": item.status,
            "tipo": item.tipo,
            "signature_link_excerpt": (item.signature_link or "")[:120],
        }
        rows.append(row)
        by_key[key].append(row)

    dup_same_track = [k for k, v in by_key.items() if k[0] and len(v) >= 2]
    tracks_seen = {r["track_inferred"] for r in rows if r["autentique_id"]}
    same_aid = len({r["autentique_id"] for r in rows if r["autentique_id"]}) == 1

    if dup_same_track:
        group_type = "TRUE_DUPLICATE_SAME_TRACK"
    elif same_aid and tracks_seen <= {"jan", "luciano"} and len(rows) == 2:
        jan = sum(1 for r in rows if r["track_inferred"] == "jan")
        luc = sum(1 for r in rows if r["track_inferred"] == "luciano")
        if jan == 1 and luc == 1:
            group_type = "VALID_MULTI_TRACK"
        elif any(t == "unknown" for t in tracks_seen):
            group_type = "AMBIGUOUS_TRACK"
        else:
            group_type = "AMBIGUOUS_TRACK"
    elif any(r["track_inferred"] == "unknown" for r in rows):
        group_type = "AMBIGUOUS_TRACK"
    elif same_aid:
        group_type = "VALID_MULTI_TRACK"
    else:
        group_type = "AMBIGUOUS_TRACK"

    return group_type, rows


def _pedido_b2b_rule(name: str) -> tuple[bool, list[str], list[str]]:
    n = normalize_controle_title(name)
    pos: list[str] = []
    neg: list[str] = []
    if not _PEDIDO.search(n):
        return False, pos, ["sem token pedido"]
    pos.append("contém pedido")
    if _B2B_INDICATORS.search(n):
        pos.append("indicador comercial/B2B no título")
    else:
        neg.append("sem indicador comercial explícito")
    if _HR_NEG.search(n):
        neg.append("indicador RH")
    if _OPER_NEG.search(n):
        neg.append("indicador operacional")
    eligible = bool(pos) and "contém pedido" in pos and "indicador comercial/B2B no título" in pos
    eligible = eligible and "indicador RH" not in neg and "indicador operacional" not in neg
    return eligible, pos, neg


def _make_action(**kwargs) -> dict:
    base = {
        "action_id": str(uuid.uuid4()),
        "requires_human_approval": True,
    }
    base.update(kwargs)
    return base


def main() -> int:
    compare_path = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else "artifacts/compare-production/compare-controle-full.json",
    )
    out_dir = Path(sys.argv[2] if len(sys.argv) > 2 else "artifacts/controle-etapa2-1")
    out_dir.mkdir(parents=True, exist_ok=True)

    compare = json.loads(compare_path.read_text(encoding="utf-8"))
    rows = compare["document_diagnostics"]
    feed_ids = {r["autentique_document_id"].casefold() for r in rows}
    docs_by_id = {r["autentique_document_id"].casefold(): r for r in rows}

    token = get_api_token_from_env()
    if not token:
        raise SystemExit("MONDAY_API_TOKEN não configurada")
    index = build_controle_assinaturas_index(api_token=token)
    all_items = list(index.all_items)
    total = len(all_items)

    # --- Monday reconciliation 1607 ---
    with_id_index: list[dict] = []
    without_id: list[dict] = []
    special_cases: list[dict] = []

    for item in all_items:
        ids_index = _item_doc_ids_in_index(item, index)
        ids_link = autentique_ids_in_controle_link(item.signature_link or "")
        explicit_line = _has_explicit_autentique_id_line(item.signature_link)
        compare_says_no = _compare_without_link(item, index)

        row = {
            "monday_item_id": item.item_id,
            "title": item.name,
            "raw_link": item.signature_link or "",
            "autentique_ids_extracted": list(ids_link),
            "autentique_ids_in_index": sorted(ids_index),
            "compare_without_link": compare_says_no,
            "has_explicit_autentique_id_line": explicit_line,
        }

        if ids_index:
            with_id_index.append({**row, "bucket": "with_id_index"})
        elif explicit_line and ids_link:
            special_cases.append(
                {
                    **row,
                    "bucket": "special_explicit_id_not_indexed",
                    "reason": (
                        "linha Autentique ID no link mas item ausente de "
                        "items_by_document_id"
                    ),
                }
            )
        elif ids_link and not explicit_line:
            special_cases.append(
                {
                    **row,
                    "bucket": "special_hash_in_link_not_indexed",
                    "reason": "hash/legado no link sem indexação",
                }
            )
        else:
            without_id.append({**row, "bucket": "without_id"})

    # Items in compare without_link list (first 100 exported) - recompute full set
    compare_without_ids = {item.item_id for item in all_items if _compare_without_link(item, index)}
    etapa2_without_ids = {item["monday_item_id"] for item in without_id}
    diff_compare_more = (
        compare_without_ids - etapa2_without_ids - {r["monday_item_id"] for r in special_cases}
    )
    diff_etapa2_more = etapa2_without_ids - compare_without_ids

    diff_items: list[dict] = []
    for item in all_items:
        if item.item_id not in diff_compare_more and item.item_id not in diff_etapa2_more:
            continue
        ids_index = _item_doc_ids_in_index(item, index)
        ids_link = autentique_ids_in_controle_link(item.signature_link or "")
        diff_items.append(
            {
                "monday_item_id": item.item_id,
                "title": item.name,
                "raw_link": item.signature_link or "",
                "autentique_ids_extracted": list(ids_link),
                "compare_reason": (
                    "sem entrada em items_by_document_id"
                    if item.item_id in diff_compare_more
                    else "compare indexaria, etapa2 sem-id não"
                ),
                "etapa2_reason": (
                    "etapa2 tratava explicit Autentique ID como com-link"
                    if item.item_id in diff_compare_more
                    else "classificado sem-id na etapa2"
                ),
                "correct_bucket": (
                    "special_explicit_id_not_indexed"
                    if _has_explicit_autentique_id_line(item.signature_link) and ids_link
                    else "without_id"
                ),
            }
        )

    id_not_in_feed: list[dict] = []
    for item in all_items:
        for doc_id in _item_doc_ids_in_index(item, index):
            if doc_id not in feed_ids:
                id_not_in_feed.append(
                    {
                        "monday_item_id": item.item_id,
                        "title": item.name,
                        "autentique_id": doc_id,
                        "in_feed_298": False,
                    }
                )

    monday_recon = {
        "total": total,
        "with_id_index": len(with_id_index),
        "without_id": len(without_id),
        "special_cases": len(special_cases),
        "sum_check": len(with_id_index) + len(without_id) + len(special_cases),
        "compare_without_link_count": len(compare_without_ids),
        "id_not_in_feed_count": len(id_not_in_feed),
        "diff_44_explanation": (
            "compare usa só items_by_document_id; etapa2 anterior também contava "
            "linha 'Autentique ID:' sem indexação → special_cases"
        ),
        "special_case_breakdown": dict(Counter(r["bucket"] for r in special_cases)),
    }
    (out_dir / "monday_reconciliation.json").write_text(
        json.dumps(
            {
                "summary": monday_recon,
                "without_id_items": without_id,
                "special_cases": special_cases,
                "diff_items": diff_items,
                "id_not_in_feed": id_not_in_feed,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- ARCHIVE audit (314 ARCHIVE_LATER etapa2) ---
    etapa2_legacy_path = Path("artifacts/controle-etapa2/legacy_without_autentique_id.json")
    etapa2_legacy = json.loads(etapa2_legacy_path.read_text(encoding="utf-8"))
    archive_later_ids = {
        row["monday_item_id"]: row
        for row in etapa2_legacy["items"]
        if row.get("classification") == "ARCHIVE_LATER"
    }
    item_by_id = {i.item_id: i for i in all_items}

    archive_audit: list[dict] = []
    evidence_dist = Counter()
    plan_class_dist = Counter()
    executable_archive = 0
    missing_from_live = 0
    for item_id, legacy_row in sorted(archive_later_ids.items()):
        item = item_by_id.get(item_id)
        if item is None:
            missing_from_live += 1
            continue
        ev = _archive_evidence(
            item,
            index,
            etapa2_reason=legacy_row.get("classification_reason"),
        )
        evidence_dist[ev["evidence_type"]] += 1
        plan_class = ev["plan_classification_v2"]
        plan_class_dist[plan_class] += 1
        if ev["executable_archive"]:
            executable_archive += 1
        archive_audit.append(
            {
                "monday_item_id": item.item_id,
                "title": item.name,
                "group": item.group_id,
                "status": item.status,
                "tipo": item.tipo,
                "autentique_id": (
                    autentique_ids_in_controle_link(item.signature_link or "")[0]
                    if autentique_ids_in_controle_link(item.signature_link or "")
                    else None
                ),
                "etapa2_classification_reason": legacy_row.get("classification_reason"),
                **ev,
            }
        )

    (out_dir / "archive_audit_314.json").write_text(
        json.dumps(
            {
                "summary": {
                    "etapa2_archive_later_count": len(archive_later_ids),
                    "audited_from_live_index": len(archive_audit),
                    "missing_from_live_index": missing_from_live,
                    "evidence_type_distribution": dict(evidence_dist),
                    "plan_classification_v2_distribution": dict(plan_class_dist),
                    "executable_archive_count": executable_archive,
                    "reclassified_from_executable_archive": len(archive_audit) - executable_archive,
                    "title_pattern_only_count": evidence_dist.get("title_pattern_only", 0),
                    "rule": (
                        "Nenhum ARCHIVE executável: title_pattern_only e URL isolada "
                        "rebaixados para PROBABLE_ARCHIVE_REVIEW ou MANUAL_REVIEW"
                    ),
                },
                "items": archive_audit,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- Duplicate reaudit ---
    dup_groups_raw = find_duplicate_normalized_names(index)
    dup_results: list[dict] = []
    dup_type_counts = Counter()
    for normalized, entries in dup_groups_raw:
        gtype, items = _classify_duplicate_group(normalized, entries, index)
        dup_type_counts[gtype] += 1
        dup_results.append(
            {
                "normalized_title": normalized,
                "group_classification": gtype,
                "items": items,
            }
        )

    (out_dir / "duplicate_reaudit.json").write_text(
        json.dumps(
            {
                "summary": dict(dup_type_counts),
                "explanation_vs_duplicate_items_zero": (
                    "compare.duplicate_items=0 conta só >1 item na MESMA track "
                    "(jan ou luciano) para o mesmo doc Autentique. "
                    "Os 55 grupos TRUE_DUPLICATE etapa2 usavam mesmo título normalizado + "
                    "mesmo ID sem distinguir tracks — incluía VALID_MULTI_TRACK Jan+Luciano."
                ),
                "groups": dup_results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- Missing tracks math ---
    missing_docs = [
        r
        for r in rows
        if r.get("proposed_action") == "missing_track"
        and r.get("scope_classification") == "eligible"
    ]
    human_class: dict[str, list] = defaultdict(list)
    for r in missing_docs:
        legacy = r.get("legacy_items_without_autentique_id") or []
        expected = sorted(r.get("expected_tracks") or [])
        missing_t = sorted(r.get("missing_tracks") or [])
        if legacy:
            hc = "NEEDS_REVIEW"
        elif r.get("scope_reason") in {"contract_domain", "supplemental_document"}:
            hc = "CONFIRMED_CREATE_LATER"
        elif expected:
            hc = "CONFIRMED_CREATE_LATER"
        else:
            hc = "NEEDS_REVIEW"
        human_class[hc].append(
            {
                "document_name": r["document_name"],
                "autentique_document_id": r["autentique_document_id"],
                "missing_tracks": missing_t,
                "legacy_items": legacy,
            }
        )

    missing_math = []
    for hc, docs in human_class.items():
        tracks = sum(len(d["missing_tracks"]) for d in docs)
        missing_math.append(
            {"human_classification": hc, "documents": len(docs), "missing_tracks": tracks}
        )

    (out_dir / "missing_tracks_math.json").write_text(
        json.dumps(
            {
                "rows": missing_math,
                "total_documents": len(missing_docs),
                "total_missing_tracks": sum(r["missing_tracks"] for r in missing_math),
                "create_track_v2_expected": sum(
                    r["missing_tracks"]
                    for r in missing_math
                    if r["human_classification"] == "CONFIRMED_CREATE_LATER"
                ),
                "excluded_needs_review_tracks": sum(
                    r["missing_tracks"]
                    for r in missing_math
                    if r["human_classification"] == "NEEDS_REVIEW"
                ),
                "note": "57 CREATE v1 = 61 - 4 tracks dos 4 NEEDS_REVIEW (1 track cada)",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- Pedido B2B 11 docs ---
    pedido_docs = [
        r
        for r in rows
        if r.get("scope_classification") == "manual_review"
        and _PEDIDO.search(normalize_controle_title(r.get("document_name") or ""))
    ]
    pedido_analysis = []
    for r in pedido_docs:
        name = r["document_name"]
        rule_ok, pos, neg = _pedido_b2b_rule(name)
        similar = [
            d["document_name"]
            for d in rows
            if d["autentique_document_id"] != r["autentique_document_id"]
            and normalized_controle_titles_equal(name, d["document_name"])
        ]
        pedido_analysis.append(
            {
                "document_name": name,
                "autentique_document_id": r["autentique_document_id"],
                "signers": r.get("signers"),
                "scope_reason": r.get("scope_reason"),
                "why_b2b": pos,
                "negative_indicators": neg,
                "proposed_rule_match": rule_ok,
                "similar_titles_in_feed": similar[:3],
                "existing_monday_tracks": sorted(r.get("existing_tracks") or []),
            }
        )

    # retrospective on 298
    retro_tp: list[str] = []
    retro_fp: list[str] = []
    retro_new: list[str] = []
    for r in rows:
        name = r["document_name"]
        rule_ok, _, _ = _pedido_b2b_rule(name)
        scope = r.get("scope_classification")
        if rule_ok and scope == "manual_review":
            retro_new.append(name)
        if rule_ok and scope == "eligible":
            retro_tp.append(name)
        if rule_ok and scope == "ineligible":
            retro_fp.append(name)

    (out_dir / "pedido_b2b_rule_analysis.json").write_text(
        json.dumps(
            {
                "proposed_rule": (
                    "pedido + indicador comercial no título "
                    "(b2b|fornec|comercial|parceria|bonific|reposic|mlm|performance|"
                    "brass hill|conforto|nobilis|stick rio|glam) "
                    "E ausência de indicadores RH/operacionais"
                ),
                "documents_manual_review_pedido": pedido_analysis,
                "retrospective_298": {
                    "true_positives_apparent": retro_tp,
                    "false_positives_apparent": retro_fp,
                    "additional_would_become_eligible": retro_new,
                    "counts": {
                        "tp": len(retro_tp),
                        "fp": len(retro_fp),
                        "new_eligible": len(retro_new),
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- Other scope rules ---
    scope_rules = {
        "cessao_eligible": _CESSAO,
        "parceria_eligible": _PARCERIA,
        "rh_mensal_ineligible": _RH_MENSAL,
    }
    scope_impact = {}
    for rule_name, pattern in scope_rules.items():
        matched = [
            {
                "document_name": r["document_name"],
                "autentique_document_id": r["autentique_document_id"],
                "current_scope": r.get("scope_classification"),
            }
            for r in rows
            if pattern.search(normalize_controle_title(r["document_name"]))
        ]
        scope_impact[rule_name] = {
            "count": len(matched),
            "would_change": [
                m
                for m in matched
                if (rule_name.endswith("eligible") and m["current_scope"] != "eligible")
                or (rule_name.endswith("ineligible") and m["current_scope"] != "ineligible")
            ],
            "titles": [m["document_name"] for m in matched],
        }

    (out_dir / "scope_rules_impact.json").write_text(
        json.dumps(scope_impact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # --- remediation_plan_v2 ---
    actions: list[dict] = []
    accounted_items = set()

    def _account(item_id: str | None) -> None:
        if item_id:
            accounted_items.add(item_id)

    # CREATE_TRACK only CONFIRMED
    for hc, docs in human_class.items():
        if hc != "CONFIRMED_CREATE_LATER":
            continue
        for d in docs:
            r = docs_by_id[d["autentique_document_id"].casefold()]
            for track in d["missing_tracks"]:
                existing = set(r.get("existing_tracks") or [])
                if track in existing:
                    continue
                actions.append(
                    _make_action(
                        action_type="CREATE_TRACK",
                        autentique_document_id=d["autentique_document_id"],
                        track=track,
                        reason="eligible confirmed, track ausente, sem legado pendente",
                        confidence="high",
                        source_of_truth="autentique_expected_tracks",
                    ),
                )

    # LINK - only unique high confidence from legacy suggestions in compare
    sug_by_item: dict[str, list] = defaultdict(list)
    for s in compare.get("legacy_link_suggestions") or []:
        if s.get("confidence") == "high" and s.get("match_reason") == "exact_title":
            sug_by_item[s["monday_item_id"]].append(s)
    for item_id, sugs in sug_by_item.items():
        if len(sugs) != 1:
            actions.append(
                _make_action(
                    action_type="MANUAL_REVIEW",
                    monday_item_id=item_id,
                    reason="múltiplos candidatos link legado",
                    confidence="low",
                    source_of_truth="legacy_link_suggestions",
                ),
            )
            _account(item_id)
            continue
        s = sugs[0]
        actions.append(
            _make_action(
                action_type="LINK",
                autentique_document_id=s["autentique_document_id"],
                monday_item_id=item_id,
                reason=s["match_reason"],
                confidence="high",
                source_of_truth="legacy_exact_title_unique",
            ),
        )
        _account(item_id)

    # ARCHIVE v2 - only executable (none expected from title/URL alone)
    for a in archive_audit:
        _account(a["monday_item_id"])
        plan_class = a["plan_classification_v2"]
        if plan_class == "ARCHIVE" and a.get("executable_archive"):
            actions.append(
                _make_action(
                    action_type="ARCHIVE",
                    monday_item_id=a["monday_item_id"],
                    reason=a["classification_reason"],
                    confidence=a["confidence"],
                    source_of_truth=a["evidence_type"],
                ),
            )
        elif plan_class == "PROBABLE_ARCHIVE_REVIEW":
            actions.append(
                _make_action(
                    action_type="PROBABLE_ARCHIVE_REVIEW",
                    monday_item_id=a["monday_item_id"],
                    reason=a["classification_reason"],
                    confidence=a["confidence"],
                    source_of_truth=a["evidence_type"],
                ),
            )
        elif plan_class == "MANUAL_REVIEW":
            actions.append(
                _make_action(
                    action_type="MANUAL_REVIEW",
                    monday_item_id=a["monday_item_id"],
                    reason=a["classification_reason"],
                    confidence=a["confidence"],
                    source_of_truth=a["evidence_type"],
                ),
            )

    # Status divergences
    for r in rows:
        current = r.get("status_current_by_track") or {}
        expected = r.get("status_expected_by_track") or {}
        scope = r.get("scope_classification")
        for track, exp in expected.items():
            cur = current.get(track)
            if cur is None or (cur or "").casefold().strip() == (exp or "").casefold().strip():
                continue
            if scope == "eligible":
                actions.append(
                    _make_action(
                        action_type="UPDATE_STATUS",
                        autentique_document_id=r["autentique_document_id"],
                        track=track,
                        current_state={"status": cur},
                        desired_state={"status": exp},
                        reason="status_behind_autentique",
                        confidence="high",
                        source_of_truth="autentique_signer_state",
                    ),
                )
            elif scope == "ineligible":
                actions.append(
                    _make_action(
                        action_type="PROBABLE_ARCHIVE_REVIEW",
                        autentique_document_id=r["autentique_document_id"],
                        track=track,
                        reason="ineligible com item no controle",
                        confidence="medium",
                        source_of_truth="scope_ineligible",
                    ),
                )
            else:
                actions.append(
                    _make_action(
                        action_type="MANUAL_REVIEW",
                        autentique_document_id=r["autentique_document_id"],
                        track=track,
                        reason="status divergente em manual_review",
                        confidence="low",
                        source_of_truth="status_divergence",
                    ),
                )

    # Duplicates TRUE_DUPLICATE_SAME_TRACK only
    for g in dup_results:
        if g["group_classification"] != "TRUE_DUPLICATE_SAME_TRACK":
            continue
        for it in g["items"][1:]:
            actions.append(
                _make_action(
                    action_type="MANUAL_REVIEW",
                    monday_item_id=it["monday_item_id"],
                    reason="duplicata mesma track e mesmo Autentique ID",
                    confidence="high",
                    source_of_truth="duplicate_same_track",
                ),
            )
            _account(it["monday_item_id"])

    # NO_ACTION / MANUAL_REVIEW for remaining without_id non-HR
    for item in without_id:
        _account(item["monday_item_id"])
        if not any(a.get("monday_item_id") == item["monday_item_id"] for a in actions):
            actions.append(
                _make_action(
                    action_type="NO_ACTION",
                    monday_item_id=item["monday_item_id"],
                    reason="sem match forte; fora do plano executável",
                    confidence="low",
                    source_of_truth="legacy_unmatched",
                ),
            )

    # Items com ID indexado ou special cases — contabilização explícita
    for row in with_id_index:
        _account(row["monday_item_id"])
        if not any(a.get("monday_item_id") == row["monday_item_id"] for a in actions):
            actions.append(
                _make_action(
                    action_type="NO_ACTION",
                    monday_item_id=row["monday_item_id"],
                    reason="já vinculado por Autentique ID no índice",
                    confidence="high",
                    source_of_truth="indexed_autentique_id",
                ),
            )
    for row in special_cases:
        _account(row["monday_item_id"])
        if not any(a.get("monday_item_id") == row["monday_item_id"] for a in actions):
            actions.append(
                _make_action(
                    action_type="MANUAL_REVIEW",
                    monday_item_id=row["monday_item_id"],
                    reason=row.get("reason", "caso especial link/id"),
                    confidence="medium",
                    source_of_truth="special_case_link_id",
                ),
            )

    # Security validation
    violations: list[dict] = []
    seen_create: set[tuple[str, str]] = set()
    for act in actions:
        at = act["action_type"]
        if at == "ARCHIVE" and act.get("source_of_truth") == "title_pattern_only":
            violations.append({"rule": "archive_title_only", "action_id": act["action_id"]})
        if at == "CREATE_TRACK":
            doc_id = (act.get("autentique_document_id") or "").casefold()
            row = docs_by_id.get(doc_id, {})
            if row.get("scope_classification") != "eligible":
                violations.append({"rule": "create_non_eligible", "action_id": act["action_id"]})
            track = act.get("track")
            if track and track not in set(row.get("expected_tracks") or []):
                violations.append(
                    {"rule": "create_unexpected_track", "action_id": act["action_id"]}
                )
            legacy = row.get("legacy_items_without_autentique_id") or []
            if legacy:
                violations.append(
                    {"rule": "create_with_unresolved_legacy", "action_id": act["action_id"]}
                )
            key = (doc_id, track or "")
            if key in seen_create:
                violations.append({"rule": "duplicate_create", "action_id": act["action_id"]})
            seen_create.add(key)
        if at == "LINK":
            mid = act.get("monday_item_id")
            if mid and len(sug_by_item.get(mid, [])) > 1:
                violations.append(
                    {"rule": "link_multiple_candidates", "action_id": act["action_id"]}
                )

    unaccounted = {item.item_id for item in all_items} - accounted_items
    if unaccounted:
        violations.append(
            {
                "rule": "items_not_accounted",
                "count": len(unaccounted),
                "sample": list(sorted(unaccounted))[:5],
            }
        )

    action_counts = Counter(a["action_type"] for a in actions)
    confidence_counts = Counter(a.get("confidence") for a in actions)
    human_approval = sum(1 for a in actions if a.get("requires_human_approval"))

    needs_more_review_signals = []
    if violations:
        needs_more_review_signals.append("plan_v2_violations")
    if executable_archive > 0:
        needs_more_review_signals.append("executable_archive_present")
    if dup_type_counts.get("TRUE_DUPLICATE_SAME_TRACK", 0) > 0:
        needs_more_review_signals.append("true_duplicate_same_track")
    if dup_type_counts.get("AMBIGUOUS_TRACK", 0) > 0:
        needs_more_review_signals.append("ambiguous_track_groups")
    if missing_from_live > 0:
        needs_more_review_signals.append("archive_items_missing_from_live")

    final_verdict = (
        "READY_FOR_CONTROLLED_REMEDIATION"
        if not needs_more_review_signals and len(violations) == 0
        else "NEEDS_MORE_REVIEW"
    )

    plan_v2 = {
        "version": "v2",
        "generated_from_compare_sha": compare.get("run_metadata", {}).get("git_sha"),
        "write_policy": {
            "CONTROLE_WRITE_ENABLED": False,
            "CONTROLE_PAUSE_CREATE": True,
            "mutations_executed": False,
        },
        "actions": actions,
        "summary": {
            "actions_by_type": dict(action_counts),
            "confidence": dict(confidence_counts),
            "requires_human_approval": human_approval,
            "safety_violations": violations,
            "violation_count": len(violations),
            "final_verdict": final_verdict,
            "needs_more_review_signals": needs_more_review_signals,
        },
    }
    (out_dir / "controle-remediation-plan-v2.json").write_text(
        json.dumps(plan_v2, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    final_summary = {
        "final_verdict": final_verdict,
        "monday": monday_recon,
        "archives": {
            "etapa2_archive_later": len(archive_later_ids),
            "audited": len(archive_audit),
            "executable_archive": executable_archive,
            "probable_archive_review": plan_class_dist.get("PROBABLE_ARCHIVE_REVIEW", 0),
            "manual_review": plan_class_dist.get("MANUAL_REVIEW", 0),
            "evidence_distribution": dict(evidence_dist),
        },
        "duplicates": dict(dup_type_counts),
        "missing": {
            "math": missing_math,
            "create_track_v2": action_counts.get("CREATE_TRACK", 0),
            "needs_review_tracks_excluded": sum(
                r["missing_tracks"]
                for r in missing_math
                if r["human_classification"] == "NEEDS_REVIEW"
            ),
        },
        "scope_pedido_retro": {
            "new_eligible": len(retro_new),
            "fp": len(retro_fp),
            "fn": sum(
                1
                for r in rows
                if r.get("scope_classification") == "manual_review"
                and _PEDIDO.search(normalize_controle_title(r.get("document_name") or ""))
                and not _pedido_b2b_rule(r["document_name"])[0]
            ),
        },
        "plan_v2_actions": dict(action_counts),
        "plan_v2_confidence": dict(confidence_counts),
        "violations": len(violations),
        "needs_more_review_signals": needs_more_review_signals,
    }
    (out_dir / "etapa2_1_summary.json").write_text(
        json.dumps(final_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(final_summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
