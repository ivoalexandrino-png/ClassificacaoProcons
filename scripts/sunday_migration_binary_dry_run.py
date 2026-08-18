#!/usr/bin/env python3
"""Dry-run metadata dos W1 binary-deferred (sem download/upload/write)."""

from __future__ import annotations

import json
import sys

from classificacao_procons.migration.apply_writer import fetch_monday_apply_sources
from classificacao_procons.migration.asset_pipeline import classify_binary_item_ready
from classificacao_procons.migration.dispositions import Disposition
from classificacao_procons.migration.dry_run import run_dry_run
from classificacao_procons.migration.executor import (
    BOARD_ALLOWLIST,
    build_execution_plan,
    load_persistent_ledger,
    sunday_config_from_test_env,
)
from classificacao_procons.migration.mappings import build_board_plan, sunday_board_by_monday_map
from classificacao_procons.migration.monday_asset_metadata import fetch_item_assets_metadata
from classificacao_procons.migration.monday_inventory import fetch_board_inventory
from classificacao_procons.migration.source_completeness import check_source_completeness_for_sources
from classificacao_procons.migration.sunday_snapshot import snapshot_from_live_client
from classificacao_procons.migration.user_mapping import load_user_mapping_policy
from classificacao_procons.monday.client import get_api_token_from_env
from classificacao_procons.sunday.client import SundayClient

PROCONS = "4944254220"
SUNDAY = "82"


def main() -> int:
    token = get_api_token_from_env()
    if not token:
        print(json.dumps({"abort": "MONDAY_API_TOKEN ausente"}))
        return 2

    client = SundayClient(sunday_config_from_test_env())
    snapshots = snapshot_from_live_client(client, list(BOARD_ALLOWLIST.values()))
    snapshot = snapshots[SUNDAY]
    inventory = fetch_board_inventory(token, PROCONS)
    policy = load_user_mapping_policy()
    report, _, _ = run_dry_run(
        {PROCONS: inventory},
        snapshots,
        user_policy=policy,
        users_mapped=set(policy.exact_match_ids),
    )
    board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
    ledger = load_persistent_ledger()
    migrated = {
        str(r["monday_item_id"])
        for r in ledger.values()
        if r.get("monday_board_id") == PROCONS and r.get("migration_status") == "migrated"
    }
    wave1 = {
        r.monday_item_id for r in report.items if r.monday_board_id == PROCONS and r.wave == "WAVE_1"
    }
    remaining = wave1 - migrated
    items_by_id = {item.item_id: item for item in inventory.items}
    binary_ids = sorted(i for i in remaining if items_by_id[i].file_count > 0)
    assets_by_item = fetch_item_assets_metadata(token, board_id=PROCONS, item_ids=set(binary_ids))
    apply_sources = fetch_monday_apply_sources(token, PROCONS, item_ids=set(binary_ids))

    full_plan = build_execution_plan(
        inventory=inventory,
        report=report,
        wave=1,
        max_items=99999,
        user_policy=policy,
        persistent_ledger=ledger,
    )
    ops = {op.monday_item_id: op for op in full_plan.operations}
    results = {
        (r.monday_board_id, r.monday_item_id): r
        for r in report.items
        if r.monday_board_id == PROCONS
    }

    rows = []
    counts = {
        "MANUAL": 0,
        "ERROR": 0,
        "blocked": 0,
        "READY": 0,
    }
    pdf_assets = 0
    jpeg_assets = 0
    single_items = 0
    multi_items = 0

    for item_id in binary_ids:
        item = items_by_id[item_id]
        op = ops[item_id]
        result = results[(PROCONS, item_id)]
        assets = assets_by_item[item_id]
        completeness = check_source_completeness_for_sources(
            inventory=inventory,
            board_plan=board_plan,
            apply_sources=apply_sources,
            item_ids=frozenset({item_id}),
            sunday_snapshot=snapshot,
        )
        ready, reason = classify_binary_item_ready(
            disposition=result.disposition,
            classification=result.classification,
            blocked_reason=op.blocked_reason,
            completeness_ok=completeness.ok,
            asset_count=len(assets),
        )
        if result.classification == "MANUAL":
            counts["MANUAL"] += 1
        if result.classification == "ERROR":
            counts["ERROR"] += 1
        if op.blocked_reason:
            counts["blocked"] += 1
        if ready:
            counts["READY"] += 1
        if len(assets) == 1:
            single_items += 1
        else:
            multi_items += 1
        for asset in assets:
            ext = (asset.file_extension or "").lower().lstrip(".")
            name_lower = (asset.name or "").lower()
            if ext in {"jpg", "jpeg"} or name_lower.endswith((".jpg", ".jpeg")):
                jpeg_assets += 1
            elif ext == "pdf" or name_lower.endswith(".pdf"):
                pdf_assets += 1
        rows.append(
            {
                "monday_item_id": item_id,
                "assets": len(assets),
                "disposition": result.disposition.value,
                "classification": result.classification,
                "blocked": op.blocked_reason or "",
                "completeness": "PASS" if completeness.ok else "FAIL",
                "ready": ready,
                "deferred_reason": reason,
            },
        )

    out = {
        "items": len(binary_ids),
        "assets": sum(len(assets_by_item[i]) for i in binary_ids),
        "single_asset_items": single_items,
        "multi_asset_items": multi_items,
        "pdf_assets": pdf_assets,
        "jpeg_assets": jpeg_assets,
        "MANUAL": counts["MANUAL"],
        "ERROR": counts["ERROR"],
        "blocked": counts["blocked"],
        "READY": counts["READY"],
        "rows": rows,
        "pilot_recommendation": {
            "pilot_A": {
                "item_id": "10736174113",
                "assets": 1,
                "type": "pdf",
                "reason": "1 PDF pequeno; revalidar live antes de APPLY",
            },
            "pilot_B": {
                "item_id": "11304091950",
                "assets": 4,
                "type": "jpeg",
                "reason": "4 JPG multi-asset; revalidar live antes de APPLY",
            },
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
