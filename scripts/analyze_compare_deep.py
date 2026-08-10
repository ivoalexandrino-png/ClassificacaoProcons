"""Análise offline do compare-controle-full.json (sem API)."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Allow imports from src when run from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.controle_required_tracks import (
    detect_internal_signers,
    resolve_expected_tracks,
)
from classificacao_procons.contratos.signer_identity import (
    email_matches_jan,
    email_matches_luciano,
    find_jan_signer,
    find_luciano_signer,
    name_matches_jan,
    name_matches_luciano,
    signer_is_jan,
    signer_is_luciano,
)


def _row_to_document(row: dict) -> AutentiqueDocumentSummary:
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
  return AutentiqueDocumentSummary(
      document_id=row["autentique_document_id"],
      name=row["document_name"],
      created_at=None,
      signed_pdf_url=None,
      signatures=sigs,
  )


def _track_reason(signer: AutentiqueSigner) -> str:
    if signer.email and email_matches_jan(signer.email):
        return "email_matches_jan"
    if signer.name and name_matches_jan(signer.name):
        return "name_matches_jan"
    if signer.email and email_matches_luciano(signer.email):
        return "email_matches_luciano"
    if signer.name and name_matches_luciano(signer.name):
        return "name_matches_luciano"
    return "not_internal"


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/compare-pr161/compare-controle-full.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["document_diagnostics"]
    out_dir = path.parent / "analysis"
    out_dir.mkdir(exist_ok=True)

    # 1) Signer identity table
    identity_docs: dict[str, set[str]] = defaultdict(set)
    identity_meta: dict[str, dict] = {}
    for row in rows:
        doc_id = row["autentique_document_id"]
        for s in row.get("signers") or []:
            email = (s.get("email") or "").strip().casefold() or "(sem email)"
            name = s.get("name") or "(sem nome)"
            if signer_is_jan(
                AutentiqueSigner(s["public_id"], s.get("name"), s.get("email"), None, s.get("signed_at"))
            ):
                track = "jan"
            elif signer_is_luciano(
                AutentiqueSigner(s["public_id"], s.get("name"), s.get("email"), None, s.get("signed_at"))
            ):
                track = "luciano"
            else:
                track = "-"
            key = f"{email}|{name}|{track}"
            identity_docs[key].add(doc_id)
            identity_meta[key] = {"email": email, "name": name, "track": track}

    identity_table = [
        {
            "signer_email_identity": identity_meta[k]["email"],
            "autentique_name": identity_meta[k]["name"],
            "track_attributed": identity_meta[k]["track"],
            "document_count": len(identity_docs[k]),
        }
        for k in sorted(identity_docs, key=lambda x: -len(identity_docs[x]))
    ]
    (out_dir / "signer_identity_table.json").write_text(
        json.dumps(identity_table, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Jan-only explanation stats
    jan_only_docs = []
    luc_only_docs = []
    both_docs = []
    no_internal = []
    for row in rows:
        doc = _row_to_document(row)
        exp = resolve_expected_tracks(doc)
        det = detect_internal_signers(doc)
        if exp == frozenset({"jan"}):
            jan_only_docs.append(row)
        elif exp == frozenset({"luciano"}):
            luc_only_docs.append(row)
        elif exp == frozenset({"jan", "luciano"}):
            both_docs.append(row)
        elif not exp:
            no_internal.append(row)

    docs_with_assinador = sum(
        1
        for row in rows
        if any(
            (s.get("email") or "").casefold().startswith("assinador@")
            or "assinador" in (s.get("email") or "").casefold()
            for s in row.get("signers") or []
        )
    )
    docs_with_juridico = sum(
        1
        for row in rows
        if any("juridico@b4a" in (s.get("email") or "").casefold() for s in row.get("signers") or [])
    )
    docs_with_luciano_email = sum(
        1
        for row in rows
        if any((s.get("email") or "").casefold() == "luciano@b4a.com.br" for s in row.get("signers") or [])
    )
    assinador_without_juridico_or_luc = []
    for row in rows:
        emails = [(s.get("email") or "").casefold() for s in row.get("signers") or []]
        has_a = any("assinador" in e for e in emails)
        has_l = any(
            e.startswith("juridico@b4a") or e == "luciano@b4a.com.br" for e in emails
        )
        if has_a and not has_l:
            assinador_without_juridico_or_luc.append(row["document_name"])

    # Bruno case
    bruno = next(
        (r for r in rows if "Bruno Santos de Castro" in r.get("document_name", "") and "Rescisão SOP" in r.get("document_name", "")),
        None,
    )
    bruno_detail = None
    if bruno:
        doc = _row_to_document(bruno)
        chosen_jan = find_jan_signer(doc.signatures)
        chosen_luc = find_luciano_signer(doc.signatures)
        bruno_detail = {
            "document_name": bruno["document_name"],
            "signers": [
                {
                    "public_id": s["public_id"],
                    "name": s.get("name"),
                    "email": s.get("email"),
                    "signed_at": s.get("signed_at"),
                    "track_attributed": (
                        "jan"
                        if signer_is_jan(
                            AutentiqueSigner(
                                s["public_id"],
                                s.get("name"),
                                s.get("email"),
                                None,
                                s.get("signed_at"),
                            )
                        )
                        else (
                            "luciano"
                            if signer_is_luciano(
                                AutentiqueSigner(
                                    s["public_id"],
                                    s.get("name"),
                                    s.get("email"),
                                    None,
                                    s.get("signed_at"),
                                )
                            )
                            else "-"
                        )
                    ),
                    "attribution_reason": _track_reason(
                        AutentiqueSigner(
                            s["public_id"],
                            s.get("name"),
                            s.get("email"),
                            None,
                            s.get("signed_at"),
                        )
                    ),
                }
                for s in bruno.get("signers") or []
            ],
            "find_jan_signer_public_id": chosen_jan.public_id if chosen_jan else None,
            "find_luciano_signer_public_id": chosen_luc.public_id if chosen_luc else None,
            "status_expected": bruno.get("status_expected_by_track"),
        }

    # luciano + juridico both present
    dual_luc = []
    for row in rows:
        emails = [(s.get("email") or "").casefold() for s in row.get("signers") or []]
        has_j = any(e.startswith("juridico@b4a") for e in emails)
        has_l = any(e == "luciano@b4a.com.br" for e in emails)
        if has_j and has_l:
            doc = _row_to_document(row)
            chosen = find_luciano_signer(doc.signatures)
            dual_luc.append(
                {
                    "document_name": row["document_name"],
                    "autentique_document_id": row["autentique_document_id"],
                    "signers": row.get("signers"),
                    "find_luciano_signer_email": chosen.email if chosen else None,
                    "find_luciano_signer_signed": bool(chosen and chosen.signed_at),
                    "all_juridico_signed": all(
                        s.get("signed_at")
                        for s in row.get("signers") or []
                        if (s.get("email") or "").casefold().startswith("juridico@b4a")
                    ),
                    "all_luciano_email_signed": all(
                        s.get("signed_at")
                        for s in row.get("signers") or []
                        if (s.get("email") or "").casefold() == "luciano@b4a.com.br"
                    ),
                }
            )

    # manual_review breakdown
    mr = [r for r in rows if r.get("scope_classification") == "manual_review"]
    mr_by_reason: dict[str, list[str]] = defaultdict(list)
    for r in mr:
        mr_by_reason[r.get("scope_reason") or "?"].append(r["document_name"])

    mr_summary = [
        {
            "scope_reason": reason,
            "count": len(names),
            "examples": names[:5],
        }
        for reason, names in sorted(mr_by_reason.items(), key=lambda x: -len(x[1]))
    ]

    # eligible missing_track
    em = [
        r
        for r in rows
        if r.get("proposed_action") == "missing_track"
        and r.get("scope_classification") == "eligible"
    ]
    (out_dir / "eligible_missing_track_42.json").write_text(
        json.dumps(em, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # missing tracks breakdown by scope
    scope_missing: dict[str, dict[str, int]] = defaultdict(lambda: {"docs": 0, "tracks": 0})
    for r in rows:
        mt = r.get("missing_tracks") or []
        if not mt:
            continue
        sc = r.get("scope_classification") or "?"
        scope_missing[sc]["docs"] += 1
        scope_missing[sc]["tracks"] += len(mt)

    # Monday linkage from compare payload (approximation via rows)
    linked_item_ids = set()
    for r in rows:
        for _iid, _name in r.get("duplicate_items") or []:
            linked_item_ids.add(_iid)
    docs_with_existing = sum(1 for r in rows if r.get("existing_tracks"))

    summary = {
        "jan_only_count": len(jan_only_docs),
        "luciano_only_count": len(luc_only_docs),
        "both_count": len(both_docs),
        "no_internal_count": len(no_internal),
        "docs_with_assinador_email": docs_with_assinador,
        "docs_with_juridico_email": docs_with_juridico,
        "docs_with_luciano_at_b4a": docs_with_luciano_email,
        "docs_assinador_without_juridico_or_luciano_email": assinador_without_juridico_or_luc,
        "bruno_case": bruno_detail,
        "dual_luciano_juridico_count": len(dual_luc),
        "dual_luciano_juridico_sample": dual_luc[:15],
        "manual_review_breakdown": mr_summary,
        "missing_tracks_by_scope": dict(scope_missing),
        "eligible_missing_track_count": len(em),
        "documents_with_existing_tracks_in_feed": docs_with_existing,
        "monday_items_total": data.get("monday_items_total"),
        "autentique_total": data.get("autentique_total"),
    }
    (out_dir / "analysis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
