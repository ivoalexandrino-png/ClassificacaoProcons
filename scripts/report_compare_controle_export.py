"""Gera relatório legível a partir de compare-controle-full.json (read-only)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _signer_lines(signers: list[dict]) -> list[str]:
    lines: list[str] = []
    for signer in signers:
        parts = [
            signer.get("name") or "?",
            signer.get("email") or "",
            signer.get("public_id") or "",
            "signed" if signer.get("signed_at") else "pending",
        ]
        lines.append(" | ".join(p for p in parts if p))
    return lines


def _row_brief(row: dict) -> dict:
    return {
        "document_name": row["document_name"],
        "autentique_document_id": row["autentique_document_id"],
        "signers": _signer_lines(row.get("signers") or []),
        "internal_signers_detected": row.get("internal_signers_detected"),
        "scope_classification": row.get("scope_classification"),
        "scope_reason": row.get("scope_reason"),
        "expected_tracks": row.get("expected_tracks"),
        "existing_tracks": row.get("existing_tracks"),
        "unexpected_tracks": row.get("unexpected_tracks"),
        "missing_tracks": row.get("missing_tracks"),
        "proposed_action": row.get("proposed_action"),
        "status_expected_by_track": row.get("status_expected_by_track"),
        "status_current_by_track": row.get("status_current_by_track"),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: report_compare_controle_export.py compare-controle-full.json", file=sys.stderr)
        return 1
    data = _load(Path(sys.argv[1]))
    meta = data.get("run_metadata") or {}
    diag = data.get("diagnostic_summary") or {}
    rows = data.get("document_diagnostics") or []

    print("=== RUN METADATA ===")
    print(json.dumps(meta, indent=2, ensure_ascii=False))
    print("\n=== DIAGNOSTIC SUMMARY ===")
    print(json.dumps(diag, indent=2, ensure_ascii=False))
    print(
        f"\nautentique_total={data.get('autentique_total')} "
        f"monday_items_total={data.get('monday_items_total')}"
    )

    hr_pattern = re.compile(
        r"ferias|férias|rescis|declarac|plano.*saude|plano.*saúde|admissao|admissão",
        re.I,
    )

    def pick(predicate, limit: int) -> list[dict]:
        out: list[dict] = []
        for row in rows:
            if predicate(row):
                out.append(_row_brief(row))
            if len(out) >= limit:
                break
        return out

    jan_only = pick(lambda r: r.get("expected_tracks") == ["jan"], 3)
    luc_only = pick(lambda r: r.get("expected_tracks") == ["luciano"], 3)
    both = pick(lambda r: set(r.get("expected_tracks") or []) == {"jan", "luciano"}, 3)
    ineligible = pick(lambda r: r.get("scope_classification") == "ineligible", 3)
    manual = [r for r in rows if r.get("scope_classification") == "manual_review"]
    manual_sample = [_row_brief(r) for r in manual[:20]]
    no_internal = pick(
        lambda r: not r.get("internal_signers_detected") and not r.get("expected_tracks"),
        3,
    )

    print("\n=== SAMPLES jan_only (3) ===")
    print(json.dumps(jan_only, indent=2, ensure_ascii=False))
    print("\n=== SAMPLES luciano_only (3) ===")
    print(json.dumps(luc_only, indent=2, ensure_ascii=False))
    print("\n=== SAMPLES both (3) ===")
    print(json.dumps(both, indent=2, ensure_ascii=False))
    print("\n=== SAMPLES ineligible (3) ===")
    print(json.dumps(ineligible, indent=2, ensure_ascii=False))
    print(f"\n=== manual_review total={len(manual)} sample={min(20, len(manual))} ===")
    print(json.dumps(manual_sample, indent=2, ensure_ascii=False))
    print("\n=== SAMPLES no_internal_signer (3) ===")
    print(json.dumps(no_internal, indent=2, ensure_ascii=False))

    hr_docs = [_row_brief(r) for r in rows if hr_pattern.search(r.get("document_name") or "")]
    print(f"\n=== HR-LIKE DOCS ({len(hr_docs)}) ===")
    for row in hr_docs[:25]:
        print(json.dumps(row, ensure_ascii=False))

    partial: list[dict] = []
    for row in rows:
        exp = set(row.get("expected_tracks") or [])
        if exp != {"jan", "luciano"}:
            continue
        status_exp = row.get("status_expected_by_track") or {}
        jan_exp = status_exp.get("jan")
        luc_exp = status_exp.get("luciano")
        if jan_exp != luc_exp:
            partial.append(_row_brief(row))
    print(f"\n=== PARTIAL JAN/LUCIANO STATUS ({len(partial)}) ===")
    for row in partial[:10]:
        print(json.dumps(row, ensure_ascii=False))

    unexpected_cases = [
        _row_brief(r)
        for r in rows
        if r.get("unexpected_tracks")
    ]
    print(f"\n=== UNEXPECTED_TRACKS DOCS ({len(unexpected_cases)}) ===")
    print(json.dumps(unexpected_cases, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
