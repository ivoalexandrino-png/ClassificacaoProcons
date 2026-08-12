#!/usr/bin/env python3
"""Executor Fase 3 — PLAN (default, zero escrita) e APPLY (fail-closed).

PLAN do piloto KPI:

    python scripts/sunday_migration_execute.py \
        --board 5563754463 --wave 1 --mode plan --max-items 31

APPLY nunca roda sem: --mode apply + --confirm-writes + env
SUNDAY_MIGRATION_ALLOW_APPLY=1 + gate 100% OK + snapshot revalidado.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from classificacao_procons.migration.apply_writer import (
    build_sunday_monday_id_index,
    fetch_monday_apply_sources,
    verify_applied_board,
)
from classificacao_procons.migration.dry_run import run_dry_run
from classificacao_procons.migration.executor import (
    BOARD_ALLOWLIST,
    ApplyMigrationContext,
    ExecutorAbort,
    apply_plan,
    build_execution_plan,
    build_sunday_schema_checks,
    load_persistent_ledger,
    snapshot_fingerprint,
    sunday_config_from_test_env,
)
from classificacao_procons.migration.mappings import build_board_plan, sunday_board_by_monday_map
from classificacao_procons.migration.monday_inventory import (
    fetch_board_inventory,
    inventory_from_payload,
)
from classificacao_procons.migration.sunday_snapshot import (
    load_snapshot_file,
    snapshot_from_live_client,
)
from classificacao_procons.migration.user_mapping import load_user_mapping_policy
from classificacao_procons.monday.client import get_api_token_from_env

DEFAULT_SUNDAY_SNAPSHOT = "docs/sunday-ws22-schema-snapshot-2026-08-11.json"
EXPECTED_KPI_FINGERPRINT = "a4de634dbe6b545ade7a0442"
KPI_MONDAY_BOARD = "5563754463"
KPI_SUNDAY_BOARD = "86"
KPI_TARGET_GROUP_ID = "255"
KPI_MONDAY_ID_COLUMN_ID = "554"
KPI_EXPECTED_ROWS = 31


def _find_monday_id_column(snapshot) -> str:
    for column in snapshot.columns:
        if column.label.strip().lower() == "monday id":
            return column.id
    raise ExecutorAbort("Coluna Monday ID ausente no schema live do Sunday.")


def _validate_plan_payload(payload: dict) -> None:
    counts = payload.get("counts", {})
    if counts.get("create") != KPI_EXPECTED_ROWS:
        raise ExecutorAbort(f"CREATE esperado {KPI_EXPECTED_ROWS}, obtido {counts}.")
    for action in ("adopt", "absorb", "exclude_test", "blocked"):
        if counts.get(action, 0) != 0:
            raise ExecutorAbort(f"Contagem inesperada {action}={counts.get(action)}.")
    for field in ("comments_to_create", "attachments_to_link", "relations_to_create"):
        if payload.get(field, 0) != 0:
            raise ExecutorAbort(f"Campo {field} deveria ser 0, obtido {payload.get(field)}.")
    if payload.get("relations_unresolved", 0) != 0:
        raise ExecutorAbort("relations_unresolved deveria ser 0.")
    if not payload.get("gate_ok"):
        raise ExecutorAbort("Gate fail-closed reprovado no PLAN.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", required=True, help="monday_board_id (allowlist)")
    parser.add_argument("--wave", required=True, type=int, choices=(1, 2))
    parser.add_argument("--mode", default="plan", choices=("plan", "apply"))
    parser.add_argument("--max-items", required=True, type=int)
    parser.add_argument(
        "--item-id",
        default=None,
        help=(
            "allowlist item-level: restringe PLAN/APPLY a UM monday_item_id (precisa "
            "pertencer ao --board/--wave informados; ausência ou ambiguidade aborta)"
        ),
    )
    parser.add_argument("--monday-snapshot", help="inventário sanitizado (JSON)")
    parser.add_argument("--sunday-snapshot", default=DEFAULT_SUNDAY_SNAPSHOT)
    parser.add_argument("--refresh-sunday", action="store_true")
    parser.add_argument("--ledger", default="docs/migration/monday-sunday-ledger.json")
    parser.add_argument("--out", default="/tmp/sunday-migration-plan.json")
    parser.add_argument(
        "--confirm-writes",
        action="store_true",
        help="obrigatório (junto com env) para qualquer APPLY",
    )
    parser.add_argument(
        "--apply-report-out",
        default="/tmp/sunday-migration-apply-report.json",
        help="relatório sanitizado do APPLY",
    )
    args = parser.parse_args()

    if args.board not in BOARD_ALLOWLIST:
        print(f"ABORT: board {args.board} fora da allowlist {sorted(BOARD_ALLOWLIST)}.")
        return 2

    if args.mode == "apply" and not args.confirm_writes:
        print("ABORT: APPLY exige --confirm-writes explícito.")
        return 3

    if args.mode == "apply" and os.environ.get("SUNDAY_MIGRATION_ALLOW_APPLY") != "1":
        print("ABORT: APPLY exige SUNDAY_MIGRATION_ALLOW_APPLY=1 no ambiente.")
        return 3

    if args.mode == "apply" and not args.refresh_sunday:
        print("ABORT: APPLY exige --refresh-sunday (schema live imediato).")
        return 3

    inventory_holder: dict[str, object] = {"inventory": None}

    def reload_inventory():
        if args.monday_snapshot:
            payload = json.loads(Path(args.monday_snapshot).read_text(encoding="utf-8"))
            inventory = inventory_from_payload(payload["boards"][args.board])
        else:
            token = get_api_token_from_env()
            if not token:
                raise ExecutorAbort("MONDAY_API_TOKEN ausente e sem --monday-snapshot.")
            inventory = fetch_board_inventory(token, args.board)
        inventory_holder["inventory"] = inventory
        return snapshot_fingerprint(inventory)

    if args.monday_snapshot:
        payload = json.loads(Path(args.monday_snapshot).read_text(encoding="utf-8"))
        inventory = inventory_from_payload(payload["boards"][args.board])
    else:
        token = get_api_token_from_env()
        if not token:
            print("ABORT: MONDAY_API_TOKEN ausente e sem --monday-snapshot.")
            return 2
        print(f"Lendo snapshot atual do Monday board {args.board} (somente leitura)…")
        inventory = fetch_board_inventory(token, args.board)
    inventory_holder["inventory"] = inventory

    if len(inventory.items) != KPI_EXPECTED_ROWS and args.board == KPI_MONDAY_BOARD:
        print(
            f"ABORT: Monday source rows={len(inventory.items)} "
            f"(esperado {KPI_EXPECTED_ROWS}).",
        )
        return 3

    fingerprint = snapshot_fingerprint(inventory)
    if args.board == KPI_MONDAY_BOARD and fingerprint != EXPECTED_KPI_FINGERPRINT:
        print(
            f"ABORT: fingerprint Monday divergente ({fingerprint} != "
            f"{EXPECTED_KPI_FINGERPRINT}).",
        )
        return 3

    schema_checks = []
    sunday_snapshots = {}
    client = None
    if args.refresh_sunday:
        from classificacao_procons.sunday.client import SundayClient

        client = SundayClient(sunday_config_from_test_env())
        sunday_board = BOARD_ALLOWLIST[args.board]
        sunday_snapshots = snapshot_from_live_client(client, [sunday_board])
        snapshot = sunday_snapshots[sunday_board]
        schema_checks = build_sunday_schema_checks(
            sunday_board_id=sunday_board,
            columns=list(snapshot.columns),
            groups=snapshot.groups,
        )
        print("Schema do Sunday lido ao vivo (somente GET).")
    elif Path(args.sunday_snapshot).exists():
        sunday_snapshots = load_snapshot_file(args.sunday_snapshot)

    if args.mode == "apply" and client is not None:
        sunday_items = client.list_items(KPI_SUNDAY_BOARD).items
        if len(sunday_items) != 0:
            print(f"ABORT: Sunday board {KPI_SUNDAY_BOARD} items={len(sunday_items)} (esperado 0).")
            return 3
        monday_id_column_id = _find_monday_id_column(sunday_snapshots[KPI_SUNDAY_BOARD])
        live_index = build_sunday_monday_id_index(
            client,
            board_id=KPI_SUNDAY_BOARD,
            monday_id_column_id=monday_id_column_id,
        )
        if live_index:
            print(f"ABORT: Monday IDs já existentes no Sunday: {len(live_index)}.")
            return 3
        ledger = load_persistent_ledger(args.ledger)
        ledger_hits = sum(
            1 for item in inventory.items
            if ledger.get(f"{args.board}:{item.item_id}", {}).get("migration_status") == "migrated"
        )
        if ledger_hits:
            print(f"ABORT: ledger entries existentes para KPI: {ledger_hits}.")
            return 3

    monday_id_index = {}
    if client is not None and sunday_snapshots:
        monday_id_column_id = _find_monday_id_column(
            sunday_snapshots[BOARD_ALLOWLIST[args.board]],
        )
        monday_id_index = build_sunday_monday_id_index(
            client,
            board_id=BOARD_ALLOWLIST[args.board],
            monday_id_column_id=monday_id_column_id,
        )

    policy = load_user_mapping_policy()
    report, _plans, _pulled = run_dry_run(
        {args.board: inventory},
        sunday_snapshots,
        user_policy=policy,
        users_mapped=set(policy.exact_match_ids),
    )
    plan = build_execution_plan(
        inventory=inventory,
        report=report,
        wave=args.wave,
        max_items=args.max_items,
        mode=args.mode,
        user_policy=policy,
        persistent_ledger=load_persistent_ledger(args.ledger),
        sunday_monday_id_index=monday_id_index or None,
        sunday_schema_checks=schema_checks,
        item_id_filter=args.item_id,
    )

    Path(args.out).write_text(
        json.dumps(plan.to_payload(), ensure_ascii=False, indent=2), encoding="utf-8",
    )
    payload = plan.to_payload()
    print(f"\nPLAN gravado em {args.out}")
    print(json.dumps({k: payload[k] for k in (
        "monday_board_id", "sunday_board_id", "wave", "mode", "snapshot", "counts",
        "comments_to_create", "attachments_to_link", "relations_to_create",
        "relations_unresolved", "gate_ok",
    )}, ensure_ascii=False, indent=2))
    for check in payload["gate"]:
        print(f"  gate[{'OK ' if check['ok'] else 'FAIL'}] {check['check']}: {check['detail']}")

    if args.mode == "plan":
        return 0

    try:
        _validate_plan_payload(payload)
    except ExecutorAbort as exc:
        print(f"\nABORT: {exc}")
        return 3

    if client is None:
        print("ABORT: client Sunday ausente.")
        return 3

    sunday_snapshot = sunday_snapshots[BOARD_ALLOWLIST[args.board]]
    board_plan = build_board_plan(
        inventory,
        sunday_snapshot,
        sunday_board_by_monday_map(),
    )
    monday_token = get_api_token_from_env()
    if not monday_token:
        print("ABORT: MONDAY_API_TOKEN ausente para APPLY.")
        return 2
    apply_sources = fetch_monday_apply_sources(monday_token, args.board)
    if len(apply_sources) != len(inventory.items):
        print(
            f"ABORT: apply_sources={len(apply_sources)} != "
            f"inventory={len(inventory.items)}.",
        )
        return 3

    migration_context = ApplyMigrationContext(
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources=apply_sources,
        monday_id_column_id=_find_monday_id_column(sunday_snapshot),
        target_group_id=KPI_TARGET_GROUP_ID,
    )

    print("\nIniciando APPLY (fail-fast)…")
    try:
        apply_result = apply_plan(
            plan,
            client=client,
            confirm_writes=True,
            snapshot_revalidator=reload_inventory,
            ledger_path=args.ledger,
            fail_fast=True,
            migration_context=migration_context,
        )
    except ExecutorAbort as exc:
        print(f"\nABORT: {exc}")
        return 3

    field_report = verify_applied_board(
        client=client,
        plan=plan,
        inventory=inventory,
        board_plan=board_plan,
        apply_sources=apply_sources,
        monday_id_column_id=migration_context.monday_id_column_id,
        target_group_id=KPI_TARGET_GROUP_ID,
    )

    post_plan = build_execution_plan(
        inventory=inventory_holder["inventory"],  # type: ignore[arg-type]
        report=report,
        wave=args.wave,
        max_items=args.max_items,
        mode="plan",
        user_policy=policy,
        persistent_ledger=load_persistent_ledger(args.ledger),
        sunday_monday_id_index=build_sunday_monday_id_index(
            client,
            board_id=plan.sunday_board_id,
            monday_id_column_id=migration_context.monday_id_column_id,
        ),
        sunday_schema_checks=schema_checks,
        item_id_filter=args.item_id,
    )
    post_payload = post_plan.to_payload()

    apply_report = {
        "monday_board_id": args.board,
        "sunday_board_id": plan.sunday_board_id,
        "succeeded": apply_result.succeeded,
        "failed": [{"monday_item_id": item_id, "error": err} for item_id, err in apply_result.failed],
        "not_attempted": apply_result.not_attempted,
        "writes": apply_result.write_stats,
        "field_checks_total": field_report.total,
        "field_checks_ok": field_report.ok,
        "field_checks_error": len(field_report.errors),
        "field_check_errors_sample": field_report.errors[:10],
        "post_plan_counts": post_payload.get("counts"),
        "post_plan_create": post_payload.get("counts", {}).get("create", -1),
        "post_plan_already_migrated": post_payload.get("counts", {}).get("already_migrated", 0),
    }
    Path(args.apply_report_out).write_text(
        json.dumps(apply_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\nAPPLY concluído. Relatório: {args.apply_report_out}")
    print(json.dumps({
        "succeeded": len(apply_result.succeeded),
        "failed": len(apply_result.failed),
        "not_attempted": len(apply_result.not_attempted),
        "writes": apply_result.write_stats,
        "field_checks": f"{field_report.ok}/{field_report.total}",
        "post_plan_create": post_payload.get("counts", {}).get("create"),
        "post_plan_already_migrated": post_payload.get("counts", {}).get("already_migrated"),
    }, indent=2))

    if apply_result.failed or apply_result.not_attempted:
        return 4
    if field_report.errors:
        return 5
    if post_payload.get("counts", {}).get("create", 0) != 0:
        return 6
    return 0


if __name__ == "__main__":
    sys.exit(main())
