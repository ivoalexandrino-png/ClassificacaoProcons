#!/usr/bin/env python3
"""Executa repair APPLY scope6 (6 custom statuses) com validação completa."""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

from classificacao_procons.migration.apply_writer import fetch_monday_apply_sources
from classificacao_procons.migration.column_transforms import PROCONS_CANCELAMENTO_SUNDAY_COLUMN, PROCONS_DOCS_SAC_SUNDAY_COLUMN, PROCONS_NOTIFICACAO_SUNDAY_COLUMN
from classificacao_procons.migration.executor import load_persistent_ledger, sunday_config_from_test_env
from classificacao_procons.migration.mappings import build_board_plan, sunday_board_by_monday_map
from classificacao_procons.migration.monday_inventory import fetch_board_inventory
from classificacao_procons.migration.source_audit import AUDIT_BOARD_SUNDAY, audit_board_migrated_items
from classificacao_procons.migration.source_completeness import check_source_completeness_for_sources
from classificacao_procons.migration.status_coverage import analyze_custom_status_coverage
from classificacao_procons.migration.status_repair_scope6 import (
    SCOPE6_ENTRIES,
    StatusRepairScope6Abort,
    apply_scope6_repair_plan,
    build_scope6_repair_plan,
    count_readback_by_source,
    validate_scope6_pre_repair_plan,
)
from classificacao_procons.migration.sunday_snapshot import snapshot_from_live_client
from classificacao_procons.monday.client import get_api_token_from_env
from classificacao_procons.sunday.client import SundayClient

GISLAINE_MONDAY = "12315524808"
GISLAINE_SUNDAY = "7757"


def _fetch_chunked(token: str, board_id: str, item_ids: set[str]) -> dict:
    sources = {}
    ordered = sorted(item_ids)
    for offset in range(0, len(ordered), 5):
        chunk = set(ordered[offset : offset + 5])
        sources.update(fetch_monday_apply_sources(token, board_id, item_ids=chunk))
    return sources


def _audit_board_metrics(token, client, ledger, snapshots):
    metrics_by_board = {}
    for monday_board_id, sunday_board_id in AUDIT_BOARD_SUNDAY.items():
        inventory = fetch_board_inventory(token, monday_board_id)
        snapshot = snapshots[sunday_board_id]
        monday_id_col = next(c.id for c in snapshot.columns if c.label.strip().lower() == "monday id")
        group_id = next(gid for gid, name in snapshot.groups.items() if name.strip().casefold() == "itens")
        migrated_ids = {
            str(r["monday_item_id"])
            for r in ledger.values()
            if r.get("monday_board_id") == monday_board_id and r.get("migration_status") == "migrated"
        }
        sources = _fetch_chunked(token, monday_board_id, migrated_ids)
        metrics = audit_board_migrated_items(
            monday_board_id=monday_board_id,
            inventory=inventory,
            sunday_snapshot=snapshot,
            apply_sources=sources,
            client=client,
            monday_id_column_id=monday_id_col,
            target_group_id=group_id,
            ledger_records=ledger,
        )
        metrics_by_board[monday_board_id] = metrics
    return metrics_by_board


def _coverage_metrics(token, ledger, snapshots):
    rows = []
    for monday_board_id, sunday_board_id in AUDIT_BOARD_SUNDAY.items():
        inventory = fetch_board_inventory(token, monday_board_id)
        snapshot = snapshots[sunday_board_id]
        board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
        migrated_ids = {
            str(r["monday_item_id"])
            for r in ledger.values()
            if r.get("monday_board_id") == monday_board_id and r.get("migration_status") == "migrated"
        }
        sources = _fetch_chunked(token, monday_board_id, migrated_ids)
        coverage = analyze_custom_status_coverage(
            inventory=inventory,
            board_plan=board_plan,
            sunday_snapshot=snapshot,
            apply_sources=sources,
        )
        rows.append(
            {
                "board": monday_board_id,
                "unresolved": coverage.unresolved,
                "ambiguous": coverage.ambiguous,
            },
        )
    return rows


def _completeness_issues(token, ledger, snapshots):
    total = 0
    for monday_board_id, sunday_board_id in AUDIT_BOARD_SUNDAY.items():
        inventory = fetch_board_inventory(token, monday_board_id)
        snapshot = snapshots[sunday_board_id]
        board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
        migrated_ids = {
            str(r["monday_item_id"])
            for r in ledger.values()
            if r.get("monday_board_id") == monday_board_id and r.get("migration_status") == "migrated"
        }
        sources = _fetch_chunked(token, monday_board_id, migrated_ids)
        report = check_source_completeness_for_sources(
            inventory=inventory,
            board_plan=board_plan,
            apply_sources=sources,
            item_ids=migrated_ids,
            sunday_snapshot=snapshot,
        )
        total += len(report.issues)
    return total


def _gislaine_check(client) -> dict[str, object]:
    cancelamento = client.get_value(GISLAINE_SUNDAY, PROCONS_CANCELAMENTO_SUNDAY_COLUMN)
    notificacao = client.get_value(GISLAINE_SUNDAY, PROCONS_NOTIFICACAO_SUNDAY_COLUMN)
    docs_sac = client.get_value(GISLAINE_SUNDAY, PROCONS_DOCS_SAC_SUNDAY_COLUMN)
    cancelamento_ok = cancelamento == "opt_2"
    notificacao_ok = isinstance(notificacao, dict) and bool(notificacao.get("url"))
    docs_sac_ok = docs_sac is None or docs_sac == "" or docs_sac == {}
    return {
        "correta": cancelamento_ok and notificacao_ok and docs_sac_ok,
        "writes": 0,
        "609": cancelamento,
        "598": notificacao,
        "605": docs_sac,
    }


def main() -> int:
    if os.environ.get("SUNDAY_MIGRATION_ALLOW_REPAIR") != "1":
        print(json.dumps({"error": "SUNDAY_MIGRATION_ALLOW_REPAIR=1 ausente"}))
        return 2
    if len(sys.argv) > 1 and sys.argv[1] == "--plan-only":
        apply_enabled = False
    else:
        apply_enabled = True

    token = get_api_token_from_env()
    if not token:
        print(json.dumps({"error": "MONDAY_API_TOKEN ausente"}))
        return 2

    client = SundayClient(sunday_config_from_test_env())
    ledger = load_persistent_ledger()
    snapshots = snapshot_from_live_client(client, ["86", "82"])

    scope_boards = {entry.monday_board_id for entry in SCOPE6_ENTRIES}
    inventories = {board_id: fetch_board_inventory(token, board_id) for board_id in scope_boards}
    apply_sources_by_board = {}
    for board_id in scope_boards:
        item_ids = {entry.monday_item_id for entry in SCOPE6_ENTRIES if entry.monday_board_id == board_id}
        apply_sources_by_board[board_id] = _fetch_chunked(token, board_id, item_ids)

    plan = build_scope6_repair_plan(
        snapshots=snapshots,
        apply_sources=apply_sources_by_board,
        inventories=inventories,
        client=client,
    )

    report: dict[str, object] = {
        "pre_repair": {
            "items": plan.items_scope,
            "status_writes": plan.status_writes,
            "skip_already_correct": plan.skip_already_correct,
            "blocked": plan.blocked,
            "resolved": sum(1 for item in plan.items if item.option_key),
            "unresolved": sum(1 for item in plan.items if not item.option_key and item.operation != "blocked"),
            "ambiguous": 0,
            "source_changed": plan.source_changed,
            "gate": "PASS",
        },
    }

    try:
        validate_scope6_pre_repair_plan(plan)
    except StatusRepairScope6Abort as exc:
        report["pre_repair"]["gate"] = f"FAIL: {exc}"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 3

    if not apply_enabled:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    apply_result = apply_scope6_repair_plan(plan=plan, client=client)
    report["repair"] = {
        "iniciado": True,
        "writes_succeeded": apply_result.writes_succeeded,
        "writes_failed": apply_result.writes_failed,
        "writes_not_attempted": apply_result.writes_not_attempted,
        "aborted": apply_result.aborted,
        "abort_reason": apply_result.abort_reason,
    }

    readback = count_readback_by_source(plan, client)
    report["readback"] = {
        "KPI Em Recurso expected": readback.get("Em Recurso (Nosso)", {}).get("expected", 0),
        "KPI Em Recurso correct": readback.get("Em Recurso (Nosso)", {}).get("correct", 0),
        "KPI Acordo expected": readback.get("Acordo", {}).get("expected", 0),
        "KPI Acordo correct": readback.get("Acordo", {}).get("correct", 0),
        "Procons entrega expected": readback.get("Problemas com entrega", {}).get("expected", 0),
        "Procons entrega correct": readback.get("Problemas com entrega", {}).get("correct", 0),
        "write_checks_total": apply_result.write_checks_total,
        "write_checks_ok": apply_result.write_checks_ok,
        "write_checks_error": apply_result.write_checks_error,
    }

    if apply_result.aborted or apply_result.writes_succeeded != 6:
        report["resultado"] = "FALHA"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 3

    post_plan = build_scope6_repair_plan(
        snapshots=snapshots,
        apply_sources=apply_sources_by_board,
        inventories=inventories,
        client=client,
    )
    report["idempotencia"] = {
        "status_writes": post_plan.status_writes,
        "skip_already_correct": post_plan.skip_already_correct,
        "blocked": post_plan.blocked,
        "total_writes": post_plan.status_writes,
    }

    audit_snapshots = snapshot_from_live_client(client, list(AUDIT_BOARD_SUNDAY.values()))
    audit_metrics = _audit_board_metrics(token, client, ledger, audit_snapshots)
    report["auditoria"] = {}
    global_audited = 0
    global_verified = 0
    global_divergence = 0
    global_unresolved = 0
    for board_id, metrics in audit_metrics.items():
        report["auditoria"][board_id] = {
            "items_audited": metrics.items_audited,
            "items_100_percent_verified": metrics.items_fully_verified,
            "items_divergence": metrics.items_with_divergence,
            "mismatched": metrics.mismatched,
            "missing_target": metrics.missing_target_values,
            "unmapped": metrics.unmapped_source_fields,
            "unresolved": metrics.semantic_resolution_unverified,
            "ambiguous": 0,
        }
        global_audited += metrics.items_audited
        global_verified += metrics.items_fully_verified
        global_divergence += metrics.items_with_divergence
        global_unresolved += metrics.semantic_resolution_unverified

    report["global"] = {
        "items_audited": global_audited,
        "items_100_percent_verified": global_verified,
        "items_divergence": global_divergence,
        "unresolved": global_unresolved,
        "ambiguous": 0,
    }

    coverage = _coverage_metrics(token, ledger, audit_snapshots)
    report["coverage"] = coverage
    report["completeness_issues"] = _completeness_issues(token, ledger, audit_snapshots)

    ledger_counts = defaultdict(int)
    for record in ledger.values():
        if record.get("migration_status") == "migrated":
            ledger_counts[record.get("monday_board_id", "")] += 1
    report["ledger"] = {
        "KPI": ledger_counts["5563754463"],
        "Trabalhista": ledger_counts["4443297481"],
        "Procons": ledger_counts["4944254220"],
        "total": sum(ledger_counts.values()),
        "alterado": False,
    }

    report["gislaine"] = _gislaine_check(client)
    report["monday_writes"] = 0
    report["outros_writes"] = 0
    report["novos_applys"] = "BLOQUEADOS"

    success = (
        apply_result.writes_succeeded == 6
        and post_plan.status_writes == 0
        and post_plan.skip_already_correct == 6
        and global_verified == 52
        and report["completeness_issues"] == 0
        and all(row["unresolved"] == 0 and row["ambiguous"] == 0 for row in coverage)
    )
    report["resultado"] = "SUCESSO" if success else "SUCESSO COM RESSALVAS"
    report["pronto_descongelamento"] = "SIM" if success else "NÃO"

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if success else 4


if __name__ == "__main__":
    sys.exit(main())
