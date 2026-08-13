#!/usr/bin/env python3
"""Diagnóstico read-only de custom status UNRESOLVED (zero writes)."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict

from classificacao_procons.migration.apply_writer import fetch_monday_apply_sources
from classificacao_procons.migration.executor import load_persistent_ledger, sunday_config_from_test_env
from classificacao_procons.migration.mappings import build_board_plan, slugify_status_key, sunday_board_by_monday_map
from classificacao_procons.migration.monday_inventory import fetch_board_inventory
from classificacao_procons.migration.source_audit import AUDIT_BOARD_SUNDAY
from classificacao_procons.migration.status_coverage import (
    TargetLiveState,
    analyze_custom_status_coverage,
    classify_status_source_vs_options,
    classify_target_live_state,
    diagnose_status_field,
)
from classificacao_procons.migration.sunday_snapshot import snapshot_from_live_client
from classificacao_procons.monday.client import get_api_token_from_env
from classificacao_procons.sunday.client import SundayClient

KPI_MONDAY = "5563754463"
KPI_STATUS_COLUMN = "status_11"
PROCONS_MONDAY = "4944254220"
PROCONS_ITEM = "11437293298"
PROCONS_STATUS_COLUMN = "status_11"


def _fetch_sources_chunked(token: str, board_id: str, item_ids: set[str], *, chunk_size: int = 5):
    sources = {}
    ordered = sorted(item_ids)
    for offset in range(0, len(ordered), chunk_size):
        chunk = set(ordered[offset : offset + chunk_size])
        sources.update(fetch_monday_apply_sources(token, board_id, item_ids=chunk))
    return sources


def _sunday_column(snapshot, *, column_id: str | None = None, key: str | None = None):
    for column in snapshot.columns:
        if column_id and column.id == column_id:
            return column
        if key and column.key == key:
            return column
    return None


def main() -> int:
    token = get_api_token_from_env()
    if not token:
        print(json.dumps({"error": "MONDAY_API_TOKEN ausente"}))
        return 2

    client = SundayClient(sunday_config_from_test_env())
    ledger = load_persistent_ledger()
    snapshots = snapshot_from_live_client(client, list(AUDIT_BOARD_SUNDAY.values()))

    report: dict[str, object] = {}

    # --- KPI unresolved cases ---
    kpi_snapshot = snapshots["86"]
    kpi_inventory = fetch_board_inventory(token, KPI_MONDAY)
    kpi_plan = build_board_plan(kpi_inventory, kpi_snapshot, sunday_board_by_monday_map())
    kpi_col_plan = next(p for p in kpi_plan.column_plans if p.monday_column_id == KPI_STATUS_COLUMN)
    kpi_sunday_col = _sunday_column(kpi_snapshot, column_id=kpi_col_plan.sunday_column_id)
    kpi_options = list((kpi_sunday_col.settings or {}).get("options", [])) if kpi_sunday_col else []

    kpi_migrated = {
        str(r["monday_item_id"]): str(r["sunday_item_id"])
        for r in ledger.values()
        if r.get("monday_board_id") == KPI_MONDAY and r.get("migration_status") == "migrated"
    }
    kpi_sources = _fetch_sources_chunked(token, KPI_MONDAY, set(kpi_migrated))

    kpi_unresolved_rows = []
    for monday_id, sunday_id in sorted(kpi_migrated.items(), key=lambda x: x[0]):
        source = kpi_sources.get(monday_id)
        if source is None:
            continue
        source_text = source.values_by_column_id.get(KPI_STATUS_COLUMN)
        if not (source_text or "").strip():
            continue
        diag = diagnose_status_field(
            source_value=source_text,
            semantic_key=slugify_status_key(source_text),
            column_options=kpi_options,
            status_mappings=kpi_plan.status_mappings.get(KPI_STATUS_COLUMN, {}),
            target_current=client.get_value(sunday_id, kpi_col_plan.sunday_column_id or ""),
        )
        if diag.resolution != "RESOLVED":
            kpi_unresolved_rows.append(
                {
                    "monday_item_id": monday_id,
                    "sunday_item_id": sunday_id,
                    "source_column_id": KPI_STATUS_COLUMN,
                    "source_value": source_text,
                    "target_column_id": kpi_col_plan.sunday_column_id,
                    "target_current": diag.target_current,
                    "classification": diag.classification,
                    "candidate_option": diag.candidate_option,
                    "target_live_state": diag.target_live_state,
                },
            )

    report["kpi_unresolved"] = kpi_unresolved_rows
    report["kpi_source_value_counts"] = dict(
        Counter(row["source_value"] for row in kpi_unresolved_rows),
    )
    report["kpi_target_options"] = {
        "column_id": kpi_sunday_col.id if kpi_sunday_col else None,
        "key": kpi_sunday_col.key if kpi_sunday_col else None,
        "type": kpi_sunday_col.type if kpi_sunday_col else None,
        "options": [
            {"option_key": opt.get("key"), "label": opt.get("label")} for opt in kpi_options
        ],
    }

    kpi_distinct = sorted({row["source_value"] for row in kpi_unresolved_rows})
    report["kpi_source_classifications"] = {
        value: classify_status_source_vs_options(
            source_value=value,
            semantic_key=slugify_status_key(value),
            column_options=kpi_options,
            status_mappings=kpi_plan.status_mappings.get(KPI_STATUS_COLUMN, {}),
        ).__dict__
        for value in kpi_distinct
    }

    # --- Procons single unresolved ---
    procons_snapshot = snapshots["82"]
    procons_inventory = fetch_board_inventory(token, PROCONS_MONDAY)
    procons_plan = build_board_plan(procons_inventory, procons_snapshot, sunday_board_by_monday_map())
    procons_col_plan = next(p for p in procons_plan.column_plans if p.monday_column_id == PROCONS_STATUS_COLUMN)
    procons_sunday_col = _sunday_column(procons_snapshot, column_id=procons_col_plan.sunday_column_id)
    procons_options = list((procons_sunday_col.settings or {}).get("options", [])) if procons_sunday_col else []

    procons_sunday_id = str(
        next(
            r["sunday_item_id"]
            for r in ledger.values()
            if r.get("monday_item_id") == PROCONS_ITEM and r.get("migration_status") == "migrated"
        ),
    )
    procons_source = fetch_monday_apply_sources(token, PROCONS_MONDAY, item_ids={PROCONS_ITEM})[PROCONS_ITEM]
    procons_source_text = procons_source.values_by_column_id.get(PROCONS_STATUS_COLUMN) or ""
    procons_diag = diagnose_status_field(
        source_value=procons_source_text,
        semantic_key=slugify_status_key(procons_source_text),
        column_options=procons_options,
        status_mappings=procons_plan.status_mappings.get(PROCONS_STATUS_COLUMN, {}),
        target_current=client.get_value(procons_sunday_id, procons_col_plan.sunday_column_id or ""),
    )
    report["procons_unresolved"] = {
        "monday_item_id": PROCONS_ITEM,
        "sunday_item_id": procons_sunday_id,
        "source_column_id": PROCONS_STATUS_COLUMN,
        "source_value": procons_source_text,
        "target_column_id": procons_col_plan.sunday_column_id,
        "target_current": procons_diag.target_current,
        "classification": procons_diag.classification,
        "candidate_option": procons_diag.candidate_option,
        "target_live_state": procons_diag.target_live_state,
    }
    report["procons_causa1_options"] = {
        "column_id": procons_sunday_col.id if procons_sunday_col else None,
        "key": procons_sunday_col.key if procons_sunday_col else None,
        "type": procons_sunday_col.type if procons_sunday_col else None,
        "options": [
            {"option_key": opt.get("key"), "label": opt.get("label")} for opt in procons_options
        ],
    }
    report["procons_source_classification"] = classify_status_source_vs_options(
        source_value=procons_source_text,
        semantic_key=slugify_status_key(procons_source_text),
        column_options=procons_options,
        status_mappings=procons_plan.status_mappings.get(PROCONS_STATUS_COLUMN, {}),
    ).__dict__

    # --- Global coverage ---
    coverage_rows = []
    for monday_board_id, sunday_board_id in AUDIT_BOARD_SUNDAY.items():
        inventory = fetch_board_inventory(token, monday_board_id)
        snapshot = snapshots[sunday_board_id]
        board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
        migrated_ids = {
            str(r["monday_item_id"])
            for r in ledger.values()
            if r.get("monday_board_id") == monday_board_id and r.get("migration_status") == "migrated"
        }
        sources = _fetch_sources_chunked(token, monday_board_id, migrated_ids)
        coverage = analyze_custom_status_coverage(
            inventory=inventory,
            board_plan=board_plan,
            sunday_snapshot=snapshot,
            apply_sources=sources,
        )
        coverage_rows.append(
            {
                "board": monday_board_id,
                "sunday_board": sunday_board_id,
                "distinct_source_values": coverage.distinct_source_values,
                "resolved": coverage.resolved,
                "unresolved": coverage.unresolved,
                "ambiguous": coverage.ambiguous,
            },
        )
    report["global_coverage"] = coverage_rows

    # --- Target live states for all 6 ---
    target_states: dict[str, list[str]] = defaultdict(list)
    for row in kpi_unresolved_rows + [report["procons_unresolved"]]:
        state = row["target_live_state"]
        target_states[state].append(f"{row['monday_item_id']}:{row['sunday_item_id']}")
    report["target_live_states"] = dict(target_states)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
