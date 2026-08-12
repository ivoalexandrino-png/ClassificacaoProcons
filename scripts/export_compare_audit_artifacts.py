"""Gera artefatos de auditoria a partir de compare-controle-full.json."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.signer_identity import (
    signer_is_jan,
    signer_is_luciano,
)


def _suggest_human_scope(row: dict) -> str:
    name = (row.get("document_name") or "").casefold()
    reason = row.get("scope_reason") or ""
    if re.search(r"\bferias\b|\bférias\b|\brescis|\bdeclarac|\badmiss", name):
        return "ineligible"
    if re.search(r"\bpedido\b", name) and "contrato b2b" not in name:
        return "eligible"
    if re.search(r"\bcontrato\b.*\bb2b\b|\bcontrato\b.*\bfornec|\bminuta\b.*\bparceria", name):
        return "eligible"
    if re.search(r"\bcontrato mensal\b|\btermo de adesão\b", name):
        return "ineligible"
    if reason == "generic_contrato_title":
        if re.search(r"\bcessao\b|\bcessão\b|\baditivo\b|\bdistrato\b|\bprocurac", name):
            return "eligible"
        if re.search(r"\bmensal\b|\brh\b|\bcolaborador", name):
            return "ineligible"
    if reason == "uncertain_domain":
        if re.search(r"\btermo de assunção\b|\bacordo\b|\bparceria\b", name):
            return "eligible"
    return "manual_review"


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/compare-pr161/compare-controle-full.json")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "/workspace/artifacts/compare-pr161")
    out.mkdir(parents=True, exist_ok=True)
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = data["document_diagnostics"]

    # Identity table (internal only + key emails)
    key_emails = Counter()
    internal_rows: list[dict] = []
    for row in rows:
        doc_id = row["autentique_document_id"]
        for s in row.get("signers") or []:
            email = (s.get("email") or "").strip().casefold() or "(sem email)"
            name = s.get("name") or "(sem nome)"
            signer = AutentiqueSigner(
                s["public_id"], s.get("name"), s.get("email"), None, s.get("signed_at")
            )
            if signer_is_jan(signer):
                track = "jan"
            elif signer_is_luciano(signer):
                track = "luciano"
            else:
                track = "-"
            key = (email, track)
            key_emails[key] += 1
            if track != "-":
                internal_rows.append(
                    {"email": email, "name": name, "track": track, "document_id": doc_id}
                )

    identity_table = [
        {
            "identidade_email": email,
            "track_atribuida": track,
            "quantidade_documentos": count,
        }
        for (email, track), count in sorted(key_emails.items(), key=lambda x: -x[1])
        if track != "-" or email in {
            "assinador@b4a.com.br",
            "juridico@b4a.com.br",
            "luciano@b4a.com.br",
        }
    ]
    # Add luciano@ even if not internal
    if ("luciano@b4a.com.br", "-") not in {(r["identidade_email"], r["track_atribuida"]) for r in identity_table}:
        c = key_emails.get(("luciano@b4a.com.br", "-"), 0)
        if c:
            identity_table.append(
                {
                    "identidade_email": "luciano@b4a.com.br",
                    "track_atribuida": "- (não mapeado)",
                    "quantidade_documentos": c,
                }
            )

    (out / "identity_table_consolidated.json").write_text(
        json.dumps(identity_table[:30], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Manual review 76
    mr = [r for r in rows if r.get("scope_classification") == "manual_review"]
    mr_by_reason: dict[str, list[dict]] = defaultdict(list)
    for r in mr:
        mr_by_reason[r.get("scope_reason") or "?"].append(r)

    breakdown = [
        {
            "scope_reason": reason,
            "quantidade": len(items),
            "exemplos": [x["document_name"] for x in items[:5]],
        }
        for reason, items in sorted(mr_by_reason.items(), key=lambda x: -len(x[1]))
    ]
    (out / "manual_review_breakdown.json").write_text(
        json.dumps(breakdown, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    mr_full = []
    suggest_counts = Counter()
    for r in mr:
        sug = _suggest_human_scope(r)
        suggest_counts[sug] += 1
        mr_full.append(
            {
                "document_name": r["document_name"],
                "autentique_document_id": r["autentique_document_id"],
                "internal_signers_detected": r.get("internal_signers_detected"),
                "scope_reason": r.get("scope_reason"),
                "expected_tracks": r.get("expected_tracks"),
                "existing_tracks": r.get("existing_tracks"),
                "sugestao_classificacao_humana": sug,
            }
        )
    (out / "manual_review_76.json").write_text(
        json.dumps(mr_full, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "manual_review_suggestion_counts.json").write_text(
        json.dumps(dict(suggest_counts), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Eligible missing 42 - enriched
    em = [
        r
        for r in rows
        if r.get("proposed_action") == "missing_track"
        and r.get("scope_classification") == "eligible"
    ]
    enriched = []
    for r in em:
        enriched.append(
            {
                "document_name": r["document_name"],
                "autentique_document_id": r["autentique_document_id"],
                "scope_reason": r.get("scope_reason"),
                "internal_signers_detected": r.get("internal_signers_detected"),
                "expected_tracks": r.get("expected_tracks"),
                "existing_tracks": r.get("existing_tracks"),
                "missing_tracks": r.get("missing_tracks"),
                "status_expected_by_track": r.get("status_expected_by_track"),
                "proposed_action": r.get("proposed_action"),
            }
        )
    (out / "eligible_missing_track_42.json").write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    groups = Counter(tuple(sorted(r["expected_tracks"])) for r in enriched)

    # Missing tracks by scope
    scope_missing: dict[str, dict[str, int]] = defaultdict(lambda: {"docs": 0, "tracks": 0})
    for r in rows:
        mt = r.get("missing_tracks") or []
        if not mt:
            continue
        sc = r.get("scope_classification") or "?"
        scope_missing[sc]["docs"] += 1
        scope_missing[sc]["tracks"] += len(mt)

    # Monday coverage
    docs_with_existing = sum(1 for r in rows if r.get("existing_tracks"))
    docs_with_unexpected = sum(1 for r in rows if r.get("unexpected_tracks"))
    monday_total = data.get("monday_items_total", 0)
    without_link = data.get("monday_without_autentique_link_count", 0)
    not_in_feed = data.get("monday_autentique_id_not_in_feed_count", 0)

    summary = {
        "identity_highlights": {
            "juridico_docs": sum(1 for r in rows if any("juridico@b4a" in (s.get("email") or "").casefold() for s in r.get("signers") or [])),
            "assinador_docs": sum(1 for r in rows if any("assinador@b4a" in (s.get("email") or "").casefold() for s in r.get("signers") or [])),
            "luciano_email_docs": sum(1 for r in rows if any((s.get("email") or "").casefold() == "luciano@b4a.com.br" for s in r.get("signers") or [])),
        },
        "track_distribution": {
            "jan_only": sum(1 for r in rows if r.get("expected_tracks") == ["jan"]),
            "luciano_only": sum(1 for r in rows if r.get("expected_tracks") == ["luciano"]),
            "both": sum(1 for r in rows if set(r.get("expected_tracks") or []) == {"jan", "luciano"}),
            "none": sum(1 for r in rows if not r.get("expected_tracks")),
        },
        "manual_review_breakdown": breakdown,
        "manual_review_suggestion_counts": dict(suggest_counts),
        "eligible_missing_groups": {
            ",".join(k) if isinstance(k, tuple) else str(k): v for k, v in groups.items()
        },
        "missing_tracks_by_scope": dict(scope_missing),
        "monday_coverage": {
            "monday_items_total": monday_total,
            "autentique_documents_in_feed": len(rows),
            "documents_with_monday_tracks_in_index": docs_with_existing,
            "documents_with_unexpected_tracks": docs_with_unexpected,
            "monday_items_without_autentique_link_count": without_link,
            "monday_items_with_id_not_in_feed_count": not_in_feed,
            "approx_items_linked_to_feed_ids": monday_total - without_link,
            "note": "unexpected_tracks só avalia itens indexados por Autentique ID nos 298 docs",
        },
    }
    (out / "audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
