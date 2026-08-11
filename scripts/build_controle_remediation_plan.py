"""Etapa 2: plano declarativo de saneamento Controle Assinaturas (sem mutations)."""

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
    controle_names_likely_same_contract,
    extract_controle_name_tokens,
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

_HR_ARCHIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
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

_PEDIDO_B2B = re.compile(r"\bpedido\b", re.I)
_CONTRATO_B2B = re.compile(r"\bcontrato\b.*\bb2b\b|\bcontrato\b.*\bfornec|\bminuta\b", re.I)
_ADITIVO = re.compile(r"\baditivo\b", re.I)
_DISTRATO = re.compile(r"\bdistrato\b", re.I)
_CESSAO = re.compile(r"\bcessao\b|\bcessão\b", re.I)
_PARCERIA = re.compile(r"\bparceria\b|\bacordo\b", re.I)
_RH_MENSAL = re.compile(r"\bcontrato\b.*\bmensal\b|\btermo de adesão\b", re.I)
_PROCURACAO = re.compile(r"\bprocurac", re.I)
_OPERACIONAL = re.compile(r"\bvaga\b.*\bgaragem\b|\bconstituic", re.I)


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
    signed_pdf = status in {"fully_signed", "signed_pdf_present"}
    return AutentiqueDocumentSummary(
        document_id=row["autentique_document_id"],
        name=row["document_name"],
        created_at=None,
        signed_pdf_url="x" if signed_pdf else None,
        signatures=sigs,
    )


def _item_has_link(item: ControleAssinaturasItem, index) -> bool:
    link = (item.signature_link or "").casefold()
    if "autentique id:" in link:
        return True
    for doc_id, indexed in index.items_by_document_id:
        if indexed.item_id == item.item_id:
            return True
    return False


def _hr_should_archive(title: str) -> bool:
    n = normalize_controle_title(title)
    return any(p.search(n) for p in _HR_ARCHIVE_PATTERNS)


def _find_autentique_candidates(
    item: ControleAssinaturasItem,
    docs_by_id: dict[str, dict],
    docs_by_norm_title: dict[str, list[str]],
    covered_ids: set[str],
) -> list[tuple[str, str, str]]:
    """Returns list of (doc_id, doc_name, match_reason)."""
    candidates: list[tuple[str, str, str, int]] = []
    link_ids = autentique_ids_in_controle_link(item.signature_link or "")
    for doc_id in link_ids:
        norm = doc_id.casefold().strip()
        if norm in docs_by_id:
            candidates.append((norm, docs_by_id[norm]["document_name"], "autentique_id_in_link", 100))

    link = (item.signature_link or "").casefold()
    if "assina.ae" in link or "autentique" in link:
        for norm, row in docs_by_id.items():
            if norm in covered_ids:
                continue
            if norm in link or (row["document_name"] or "").casefold() in link:
                candidates.append((norm, row["document_name"], "autentique_url_in_link", 95))

    norm_monday = normalize_controle_title(item.name)
    if norm_monday in docs_by_norm_title:
        for doc_id in docs_by_norm_title[norm_monday]:
            if doc_id not in covered_ids:
                candidates.append((doc_id, docs_by_id[doc_id]["document_name"], "exact_normalized_title", 100))

    for doc_id, row in docs_by_id.items():
        if doc_id in covered_ids:
            continue
        scored_reason = None
        if normalized_controle_titles_equal(item.name, row["document_name"]):
            scored_reason = ("exact_title", 100)
        elif controle_names_likely_same_contract(row["document_name"], item.name):
            scored_reason = ("strong_title_match", 80)
        if scored_reason:
            reason, score = scored_reason
            candidates.append((doc_id, row["document_name"], reason, score))

    # dedupe by doc_id keeping best score
    best: dict[str, tuple[str, str, str, int]] = {}
    for doc_id, name, reason, score in candidates:
        prev = best.get(doc_id)
        if prev is None or score > prev[3]:
            best[doc_id] = (doc_id, name, reason, score)
    return [(d, n, r) for d, n, r, _ in best.values()]


def _classify_legacy_item(
    item: ControleAssinaturasItem,
    *,
    docs_by_id: dict[str, dict],
    docs_by_norm_title: dict[str, list[str]],
    covered_ids: set[str],
) -> tuple[str, str, list[dict]]:
    if _hr_should_archive(item.name):
        return "ARCHIVE_LATER", "hr_non_contract_title", []

    candidates = _find_autentique_candidates(item, docs_by_id, docs_by_norm_title, covered_ids)
    if len(candidates) == 1 and candidates[0][2] in {
        "autentique_id_in_link",
        "autentique_url_in_link",
        "exact_normalized_title",
        "exact_title",
    }:
        doc_id, doc_name, reason = candidates[0]
        return "LINK_LATER", reason, [
            {"autentique_document_id": doc_id, "autentique_document_name": doc_name, "match_reason": reason}
        ]
    if len(candidates) >= 2:
        return "MANUAL_REVIEW", "multiple_plausible_autentique_candidates", [
            {"autentique_document_id": d, "autentique_document_name": n, "match_reason": r}
            for d, n, r in candidates[:5]
        ]
    if len(candidates) == 1 and candidates[0][2] == "strong_title_match":
        return "MANUAL_REVIEW", "only_medium_confidence_title_match", [
            {"autentique_document_id": d, "autentique_document_name": n, "match_reason": r}
            for d, n, r in candidates
        ]

    # contract-like but not in feed
    n = normalize_controle_title(item.name)
    if _CONTRATO_B2B.search(n) or _PEDIDO_B2B.search(n) or _ADITIVO.search(n) or _DISTRATO.search(n):
        return "OUTSIDE_CURRENT_FEED", "contract_like_no_feed_match", []

    return "UNMATCHED", "no_autentique_candidate_in_feed", []


def _classify_human_missing(row: dict, index) -> tuple[str, str]:
    doc_id = row["autentique_document_id"]
    legacy = row.get("legacy_items_without_autentique_id") or []
    if legacy:
        return "NEEDS_REVIEW", "há itens Monday legados com título parecido sem Autentique ID — vincular antes de criar"
    if row.get("scope_reason") == "contract_domain" and not row.get("existing_tracks"):
        return "CONFIRMED_CREATE_LATER", "Contrato B2B/comercial no escopo eligible sem filas no Controle"
    if row.get("scope_reason") == "supplemental_document":
        return "CONFIRMED_CREATE_LATER", "Aditivo/distrato/procuração eligible para filas de assinatura"
    expected = set(row.get("expected_tracks") or [])
    if expected == {"luciano"}:
        return "CONFIRMED_CREATE_LATER", "Documento com assinatura interna só Luciano (juridico@) no escopo Contratos"
    if expected == {"jan", "luciano"} or expected == {"luciano", "jan"}:
        return "CONFIRMED_CREATE_LATER", "Contrato com Jan+Luciano no Autentique, filas ausentes no Controle"
    return "NEEDS_REVIEW", "eligible mas requer confirmação humana do escopo"


def _categorize_manual_review(row: dict) -> str:
    name = row.get("document_name") or ""
    n = normalize_controle_title(name)
    if _PEDIDO_B2B.search(n):
        return "Pedido B2B"
    if _CONTRATO_B2B.search(n):
        return "contrato B2B"
    if _ADITIVO.search(n):
        return "aditivo"
    if _DISTRATO.search(n):
        return "distrato contratual"
    if _CESSAO.search(n):
        return "cessão"
    if _PARCERIA.search(n):
        return "parceria"
    if _RH_MENSAL.search(n) or _HR_ARCHIVE_PATTERNS[0].search(n):
        return "RH"
    if re.search(r"\btermo de adesão\b", n, re.I):
        return "termo de adesão"
    if _OPERACIONAL.search(n):
        return "documento operacional"
    if _PROCURACAO.search(n):
        return "procuração"
    return "realmente ambíguo"


def _suggest_scope_for_category(category: str) -> str:
    mapping = {
        "Pedido B2B": "eligible",
        "contrato B2B": "eligible",
        "aditivo": "eligible",
        "distrato contratual": "eligible",
        "cessão": "eligible",
        "parceria": "eligible",
        "procuração": "eligible",
        "RH": "ineligible",
        "termo de adesão": "ineligible",
        "documento operacional": "manual_review",
        "realmente ambíguo": "manual_review",
    }
    return mapping.get(category, "manual_review")


def _proposed_rule_for_category(category: str) -> str:
    rules = {
        "Pedido B2B": r"título contém `pedido` + signatário interno → eligible (contract_domain)",
        "contrato B2B": r"`contrato` + (`b2b`|`fornec`|`comercial`|`parceria`) → eligible",
        "aditivo": r"`aditivo` no título → eligible (supplemental_document)",
        "distrato contratual": r"`distrato` no título → eligible",
        "cessão": r"`cessão`|`cessao` + contexto comercial → eligible",
        "parceria": r"`parceria`|`termo de parceria` → eligible",
        "procuração": r"`procuração`|`procurac` → eligible",
        "RH": r"`contrato mensal`|colaborador/mês → ineligible (hr_non_contract_domain)",
        "termo de adesão": r"`termo de adesão` → ineligible",
        "documento operacional": r"manter manual_review (vaga garagem, constituição etc.)",
        "realmente ambíguo": r"sem padrão claro — permanece manual_review",
    }
    return rules.get(category, "revisão humana")


def _classify_duplicate_group(
    entries: tuple[tuple[str, str], ...],
    index,
) -> str:
    item_by_id = {item.item_id: item for item in index.all_items}
    autentique_ids: set[str] = set()
    for item_id, _ in entries:
        item = item_by_id.get(item_id)
        if item is None:
            continue
        for aid in autentique_ids_in_controle_link(item.signature_link or ""):
            autentique_ids.add(aid.casefold().strip())
    if len(autentique_ids) == 1 and len(entries) > 1:
        return "TRUE_DUPLICATE"
    if len(autentique_ids) > 1:
        return "SAME_NAME_DIFFERENT_DOCUMENT"
    # compare period tokens across names
    token_sets = [extract_controle_name_tokens(name) for _, name in entries]
    if len(token_sets) >= 2:
        shared = set.intersection(*token_sets) if token_sets else set()
        if any(_PEDIDO_B2B.search(name) or re.search(r"20\d{2}", name) for _, name in entries):
            months = set()
            for _, name in entries:
                for tok in extract_controle_name_tokens(name):
                    if re.match(r"^(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)", tok, re.I):
                        months.add(tok)
                    if re.match(r"^20\d{4}$", tok):
                        months.add(tok)
            if len(months) > 1:
                return "SAME_NAME_DIFFERENT_DOCUMENT"
    if len(entries) == 2:
        return "AMBIGUOUS"
    return "AMBIGUOUS"


def _make_action(
    *,
    action_type: str,
    autentique_id: str | None = None,
    monday_item_id: str | None = None,
    track: str | None = None,
    current_state: dict | None = None,
    desired_state: dict | None = None,
    reason: str,
    confidence: str,
    source_of_truth: str,
    requires_human_approval: bool = True,
) -> dict:
    return {
        "action_id": str(uuid.uuid4()),
        "action_type": action_type,
        "autentique_document_id": autentique_id,
        "monday_item_id": monday_item_id,
        "track": track,
        "current_state": current_state or {},
        "desired_state": desired_state or {},
        "reason": reason,
        "confidence": confidence,
        "source_of_truth": source_of_truth,
        "requires_human_approval": requires_human_approval,
    }


def _validate_plan(actions: list[dict], docs_by_id: dict[str, dict]) -> list[dict]:
    violations: list[dict] = []
    seen_create: set[tuple[str, str]] = set()
    for act in actions:
        at = act["action_type"]
        doc_id = (act.get("autentique_document_id") or "").casefold()
        track = act.get("track")
        if at == "CREATE_TRACK" and doc_id:
            row = docs_by_id.get(doc_id, {})
            scope = row.get("scope_classification")
            expected = set(row.get("expected_tracks") or [])
            if scope == "ineligible":
                violations.append({"action_id": act["action_id"], "rule": "no_create_ineligible", "detail": scope})
            if scope == "manual_review":
                violations.append({"action_id": act["action_id"], "rule": "no_create_manual_review", "detail": scope})
            if track and track not in expected:
                violations.append({"action_id": act["action_id"], "rule": "track_not_in_expected", "detail": track})
            key = (doc_id, track or "")
            if key in seen_create:
                violations.append({"action_id": act["action_id"], "rule": "duplicate_action_doc_track", "detail": key})
            seen_create.add(key)
        if at == "LINK" and act.get("confidence") != "high" and not act.get("requires_human_approval"):
            violations.append({"action_id": act["action_id"], "rule": "link_needs_approval", "detail": act.get("reason")})
        if at == "UPDATE_STATUS" and not doc_id:
            violations.append({"action_id": act["action_id"], "rule": "status_without_autentique_id", "detail": ""})
        if at == "ARCHIVE" and act.get("confidence") == "low":
            violations.append({"action_id": act["action_id"], "rule": "archive_title_only_low_confidence", "detail": ""})
    return violations


def main() -> int:
    compare_path = Path(
        sys.argv[1] if len(sys.argv) > 1 else "artifacts/compare-production/compare-controle-full.json",
    )
    out_dir = Path(sys.argv[2] if len(sys.argv) > 2 else "artifacts/controle-etapa2")
    out_dir.mkdir(parents=True, exist_ok=True)

    compare = json.loads(compare_path.read_text(encoding="utf-8"))
    rows = compare["document_diagnostics"]
    docs_by_id = {r["autentique_document_id"].casefold(): r for r in rows}
    docs_by_norm_title: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        docs_by_norm_title[normalize_controle_title(r["document_name"])].append(
            r["autentique_document_id"].casefold(),
        )

    token = get_api_token_from_env()
    if not token:
        raise SystemExit("MONDAY_API_TOKEN não configurada")
    index = build_controle_assinaturas_index(api_token=token)

    covered_ids = {d.casefold() for d, _ in index.items_by_document_id}

    # --- 42 eligible missing ---
    missing_rows = [
        r
        for r in rows
        if r.get("proposed_action") == "missing_track" and r.get("scope_classification") == "eligible"
    ]
    eligible_missing: list[dict] = []
    human_counts = Counter()
    for r in missing_rows:
        doc_id = r["autentique_document_id"]
        monday_items = []
        for item in index.items_for_document_id(doc_id):
            monday_items.append(
                {
                    "item_id": item.item_id,
                    "name": item.name,
                    "group_id": item.group_id,
                    "status": item.status,
                    "track": infer_controle_signer_track(item),
                    "autentique_ids_in_link": list(
                        autentique_ids_in_controle_link(item.signature_link or ""),
                    ),
                },
            )
        for item_id, name in r.get("legacy_items_without_autentique_id") or []:
            item = next((i for i in index.all_items if i.item_id == item_id), None)
            monday_items.append(
                {
                    "item_id": item_id,
                    "name": name,
                    "group_id": item.group_id if item else None,
                    "status": item.status if item else None,
                    "track": infer_controle_signer_track(item) if item else "legacy_unlinked",
                    "autentique_ids_in_link": list(
                        autentique_ids_in_controle_link(item.signature_link or ""),
                    )
                    if item
                    else [],
                    "legacy_match": True,
                },
            )
        human_class, human_reason = _classify_human_missing(r, index)
        human_counts[human_class] += 1
        eligible_missing.append(
            {
                "document_name": r["document_name"],
                "autentique_document_id": doc_id,
                "scope_reason": r.get("scope_reason"),
                "signers": r.get("signers"),
                "expected_tracks": sorted(r.get("expected_tracks") or []),
                "existing_tracks": sorted(r.get("existing_tracks") or []),
                "missing_tracks": sorted(r.get("missing_tracks") or []),
                "status_expected_by_track": r.get("status_expected_by_track"),
                "monday_items": monday_items,
                "proposed_action": r.get("proposed_action"),
                "human_classification": human_class,
                "human_classification_reason": human_reason,
            },
        )

    (out_dir / "eligible_missing_track_42.json").write_text(
        json.dumps(eligible_missing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # --- 76 manual review ---
    mr_rows = [r for r in rows if r.get("scope_classification") == "manual_review"]
    categories: dict[str, list[dict]] = defaultdict(list)
    scope_suggestions = Counter()
    for r in mr_rows:
        cat = _categorize_manual_review(r)
        sug = _suggest_scope_for_category(cat)
        scope_suggestions[sug] += 1
        categories[cat].append(r)

    mr_groups = []
    for cat, items in sorted(categories.items(), key=lambda x: -len(x[1])):
        mr_groups.append(
            {
                "categoria": cat,
                "quantidade": len(items),
                "classificacao_sugerida": _suggest_scope_for_category(cat),
                "regra_deterministica_proposta": _proposed_rule_for_category(cat),
                "exemplos": [i["document_name"] for i in items[:5]],
            },
        )
    (out_dir / "manual_review_76_analysis.json").write_text(
        json.dumps(
            {
                "groups": mr_groups,
                "suggested_eligible": scope_suggestions.get("eligible", 0),
                "suggested_ineligible": scope_suggestions.get("ineligible", 0),
                "suggested_manual_review": scope_suggestions.get("manual_review", 0),
                "documents": [
                    {
                        "document_name": r["document_name"],
                        "autentique_document_id": r["autentique_document_id"],
                        "scope_reason": r.get("scope_reason"),
                        "signers": r.get("signers"),
                        "categoria_negocio": _categorize_manual_review(r),
                        "classificacao_sugerida": _suggest_scope_for_category(_categorize_manual_review(r)),
                    }
                    for r in mr_rows
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- 1248 legacy without ID ---
    legacy_items = [item for item in index.all_items if not _item_has_link(item, index)]
    legacy_counts = Counter()
    legacy_details: list[dict] = []
    for item in legacy_items:
        group, reason, cands = _classify_legacy_item(
            item,
            docs_by_id=docs_by_id,
            docs_by_norm_title=docs_by_norm_title,
            covered_ids=covered_ids,
        )
        legacy_counts[group] += 1
        legacy_details.append(
            {
                "monday_item_id": item.item_id,
                "monday_item_name": item.name,
                "status": item.status,
                "group_id": item.group_id,
                "classification": group,
                "classification_reason": reason,
                "candidates": cands,
            },
        )
    (out_dir / "legacy_without_autentique_id.json").write_text(
        json.dumps(
            {"summary": dict(legacy_counts), "items": legacy_details},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- 92 duplicate normalized names ---
    dup_groups = find_duplicate_normalized_names(index)
    dup_class_counts = Counter()
    dup_details = []
    for normalized, entries in dup_groups:
        kind = _classify_duplicate_group(entries, index)
        dup_class_counts[kind] += 1
        dup_details.append(
            {
                "normalized_title": normalized,
                "classification": kind,
                "items": [{"item_id": i, "name": n} for i, n in entries],
            },
        )
    (out_dir / "duplicate_normalized_names.json").write_text(
        json.dumps(
            {"summary": dict(dup_class_counts), "groups": dup_details},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- 13 status divergences (from diagnostic rows) ---
    status_rows = []
    status_action_counts = Counter()
    for r in rows:
        current = r.get("status_current_by_track") or {}
        expected = r.get("status_expected_by_track") or {}
        for track, exp in expected.items():
            cur = current.get(track)
            if cur is None:
                continue
            if (cur or "").casefold().strip() == (exp or "").casefold().strip():
                continue
            scope = r.get("scope_classification")
            if scope == "ineligible":
                future = "ARCHIVE_LATER"
            elif scope == "eligible":
                future = "UPDATE_STATUS_LATER"
            else:
                future = "MANUAL_REVIEW"
            status_action_counts[future] += 1
            status_rows.append(
                {
                    "document_name": r["document_name"],
                    "autentique_document_id": r["autentique_document_id"],
                    "track": track,
                    "autentique_signer_status": r.get("document_status"),
                    "status_expected": exp,
                    "status_current_monday": cur,
                    "scope_classification": scope,
                    "future_action": future,
                },
            )
    (out_dir / "status_divergences.json").write_text(
        json.dumps(
            {"summary": dict(status_action_counts), "divergences": status_rows},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- remediation plan ---
    actions: list[dict] = []
    for entry in eligible_missing:
        if entry["human_classification"] != "CONFIRMED_CREATE_LATER":
            actions.append(
                _make_action(
                    action_type="MANUAL_REVIEW",
                    autentique_id=entry["autentique_document_id"],
                    reason=entry["human_classification_reason"],
                    confidence="medium",
                    source_of_truth="eligible_missing_human_review",
                ),
            )
            continue
        for track in entry["missing_tracks"]:
            actions.append(
                _make_action(
                    action_type="CREATE_TRACK",
                    autentique_id=entry["autentique_document_id"],
                    track=track,
                    current_state={"tracks_present": entry["existing_tracks"]},
                    desired_state={
                        "track": track,
                        "status": (entry.get("status_expected_by_track") or {}).get(track),
                    },
                    reason=entry["human_classification_reason"],
                    confidence="high",
                    source_of_truth="autentique_expected_tracks",
                    requires_human_approval=True,
                ),
            )

    for leg in legacy_details:
        if leg["classification"] == "LINK_LATER" and leg["candidates"]:
            c = leg["candidates"][0]
            actions.append(
                _make_action(
                    action_type="LINK",
                    autentique_id=c["autentique_document_id"],
                    monday_item_id=leg["monday_item_id"],
                    current_state={"monday_name": leg["monday_item_name"], "has_id": False},
                    desired_state={"autentique_document_id": c["autentique_document_id"]},
                    reason=leg["classification_reason"],
                    confidence="high",
                    source_of_truth="conservative_legacy_match",
                    requires_human_approval=True,
                ),
            )
        elif leg["classification"] == "ARCHIVE_LATER":
            actions.append(
                _make_action(
                    action_type="ARCHIVE",
                    monday_item_id=leg["monday_item_id"],
                    current_state={"name": leg["monday_item_name"], "status": leg["status"]},
                    desired_state={"archived": True},
                    reason=leg["classification_reason"],
                    confidence="high",
                    source_of_truth="hr_non_contract_title",
                    requires_human_approval=True,
                ),
            )
        elif leg["classification"] in {"MANUAL_REVIEW", "UNMATCHED", "OUTSIDE_CURRENT_FEED"}:
            actions.append(
                _make_action(
                    action_type="MANUAL_REVIEW" if leg["classification"] != "OUTSIDE_CURRENT_FEED" else "NO_ACTION",
                    monday_item_id=leg["monday_item_id"],
                    reason=leg["classification_reason"],
                    confidence="low" if leg["classification"] == "UNMATCHED" else "medium",
                    source_of_truth="legacy_without_id",
                    requires_human_approval=True,
                ),
            )

    for sd in status_rows:
        if sd["future_action"] == "UPDATE_STATUS_LATER":
            actions.append(
                _make_action(
                    action_type="UPDATE_STATUS",
                    autentique_id=sd["autentique_document_id"],
                    track=sd["track"],
                    current_state={"status": sd["status_current_monday"]},
                    desired_state={"status": sd["status_expected"]},
                    reason="status_behind_autentique",
                    confidence="high",
                    source_of_truth="autentique_signer_state",
                    requires_human_approval=True,
                ),
            )
        elif sd["future_action"] == "ARCHIVE_LATER":
            actions.append(
                _make_action(
                    action_type="ARCHIVE",
                    autentique_id=sd["autentique_document_id"],
                    track=sd["track"],
                    reason="ineligible_document_in_controle",
                    confidence="medium",
                    source_of_truth="scope_ineligible",
                    requires_human_approval=True,
                ),
            )

    violations = _validate_plan(actions, docs_by_id)
    action_type_counts = Counter(a["action_type"] for a in actions)
    confidence_counts = Counter(a["confidence"] for a in actions)
    approval_count = sum(1 for a in actions if a["requires_human_approval"])

    plan = {
        "generated_from_compare_sha": compare.get("run_metadata", {}).get("git_sha"),
        "monday_items_total": len(index.all_items),
        "legacy_without_id_total": len(legacy_items),
        "actions": actions,
        "summary": {
            "actions_by_type": dict(action_type_counts),
            "confidence": dict(confidence_counts),
            "requires_human_approval": approval_count,
            "safety_violations": violations,
            "eligible_missing_human": dict(human_counts),
            "legacy_classification": dict(legacy_counts),
            "duplicate_normalized": dict(dup_class_counts),
            "manual_review_suggestions": dict(scope_suggestions),
            "status_future_actions": dict(status_action_counts),
        },
    }
    (out_dir / "controle-remediation-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = {
        "eligible_missing_42": dict(human_counts),
        "manual_review_suggestions": dict(scope_suggestions),
        "legacy_without_id": dict(legacy_counts),
        "duplicate_normalized": dict(dup_class_counts),
        "status_divergences": dict(status_action_counts),
        "plan_actions_by_type": dict(action_type_counts),
        "plan_violations": len(violations),
    }
    (out_dir / "etapa2_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
