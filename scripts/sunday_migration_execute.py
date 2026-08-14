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
from dataclasses import replace
from pathlib import Path

from classificacao_procons.migration.apply_writer import (
    build_sunday_comment_marker_index,
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
KPI_EXPECTED_ROWS = 31


def _find_monday_id_column(snapshot) -> str:
    for column in snapshot.columns:
        if column.label.strip().lower() == "monday id":
            return column.id
    raise ExecutorAbort("Coluna Monday ID ausente no schema live do Sunday.")


def _find_target_group_id(snapshot, name: str = "Itens") -> str:
    matches = [
        group_id
        for group_id, group_name in snapshot.groups.items()
        if group_name.strip().casefold() == name.casefold()
    ]
    if len(matches) != 1:
        raise ExecutorAbort(
            f"Grupo destino {name!r} deve ocorrer exatamente uma vez; "
            f"encontrados {len(matches)}.",
        )
    return matches[0]


def _validate_plan_payload(
    payload: dict,
    *,
    expected_writable: int,
    allow_already_migrated: bool = False,
    expected_comments: int | None = None,
) -> None:
    counts = payload.get("counts", {})
    writable = counts.get("create", 0) + counts.get("resume", 0)
    if writable != expected_writable:
        raise ExecutorAbort(
            f"CREATE/RESUME esperado {expected_writable}, obtido {counts}.",
        )
    if expected_comments is not None:
        actual_comments = payload.get("comments_to_create", 0)
        if actual_comments != expected_comments:
            raise ExecutorAbort(
                f"comments_to_create esperado {expected_comments}, obtido {actual_comments}.",
            )
    disallowed = ("adopt", "absorb", "exclude_test", "blocked")
    if not allow_already_migrated:
        disallowed = (*disallowed, "already_migrated")
    for action in disallowed:
        if counts.get(action, 0) != 0:
            raise ExecutorAbort(f"Contagem inesperada {action}={counts.get(action)}.")
    if payload.get("relations_unresolved", 0) != 0:
        raise ExecutorAbort("relations_unresolved deveria ser 0.")
    if not payload.get("gate_ok"):
        raise ExecutorAbort("Gate fail-closed reprovado no PLAN.")


def _parse_requested_item_ids(
    item_id: str | None,
    item_ids: str | None,
) -> frozenset[str] | None:
    if item_id and item_ids:
        raise ExecutorAbort("Use --item-id OU --item-ids, não ambos.")
    if item_ids:
        raw_values = [value.strip() for value in item_ids.split(",") if value.strip()]
        if not raw_values:
            raise ExecutorAbort("--item-ids vazio.")
        if len(raw_values) != len(set(raw_values)):
            raise ExecutorAbort("--item-ids contém IDs duplicados.")
        return frozenset(raw_values)
    if item_id:
        value = item_id.strip()
        if not value:
            raise ExecutorAbort("--item-id vazio.")
        return frozenset({value})
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", required=True, help="monday_board_id (allowlist)")
    parser.add_argument("--wave", required=True, type=int, choices=(1, 2))
    parser.add_argument("--mode", default="plan", choices=("plan", "apply", "repair"))
    parser.add_argument("--max-items", required=True, type=int)
    parser.add_argument(
        "--item-id",
        help="allowlist explícita: PLAN/APPLY inclui exatamente este monday_item_id",
    )
    parser.add_argument(
        "--item-ids",
        help="allowlist explícita CSV: PLAN/APPLY inclui exatamente estes monday_item_ids",
    )
    parser.add_argument(
        "--max-comments",
        type=int,
        help="limite exato de comments_to_create do escopo autorizado",
    )
    parser.add_argument(
        "--max-operations",
        type=int,
        help=(
            "limite exato de operation_total do manifesto canônico "
            "(Sunday writes + ledger; escopo --item-ids)"
        ),
    )
    parser.add_argument(
        "--max-writes",
        type=int,
        help="alias legado de --max-operations",
    )
    parser.add_argument("--monday-snapshot", help="inventário sanitizado (JSON)")
    parser.add_argument("--sunday-snapshot", default=DEFAULT_SUNDAY_SNAPSHOT)
    parser.add_argument("--refresh-sunday", action="store_true")
    parser.add_argument("--ledger", default="docs/migration/monday-sunday-ledger.json")
    parser.add_argument("--out", default="/tmp/sunday-migration-plan.json")
    parser.add_argument(
        "--fields",
        help="repair: allowlist CSV de nomes de coluna Monday a reparar",
    )
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

    if args.mode == "repair" and args.confirm_writes:
        if os.environ.get("SUNDAY_MIGRATION_ALLOW_REPAIR") != "1":
            print("ABORT: REPAIR APPLY exige SUNDAY_MIGRATION_ALLOW_REPAIR=1 no ambiente.")
            return 3

    if args.mode == "apply" and os.environ.get("SUNDAY_MIGRATION_ALLOW_APPLY") != "1":
        print("ABORT: APPLY exige SUNDAY_MIGRATION_ALLOW_APPLY=1 no ambiente.")
        return 3

    if args.mode == "apply" and not args.refresh_sunday:
        print("ABORT: APPLY exige --refresh-sunday (schema live imediato).")
        return 3

    field_filter: frozenset[str] | None = None
    if args.fields:
        raw_fields = [value.strip() for value in args.fields.split(",") if value.strip()]
        if not raw_fields:
            raise ExecutorAbort("--fields vazio.")
        field_filter = frozenset(raw_fields)

    try:
        requested_item_ids = _parse_requested_item_ids(args.item_id, args.item_ids)
    except ExecutorAbort as exc:
        print(f"ABORT: {exc}")
        return 3

    if args.mode == "repair":
        from classificacao_procons.migration.repair_plan import (
            RepairApplyAbort,
            RepairPlanAbort,
            apply_repair_plan,
            build_repair_plan,
        )
        from classificacao_procons.sunday.client import SundayClient

        token = get_api_token_from_env()
        if not token:
            print("ABORT: MONDAY_API_TOKEN ausente para repair PLAN.")
            return 2
        if args.monday_snapshot:
            monday_payload = json.loads(
                Path(args.monday_snapshot).read_text(encoding="utf-8"),
            )
            repair_inventory = inventory_from_payload(monday_payload["boards"][args.board])
        else:
            print(f"Lendo snapshot atual do Monday board {args.board} (somente leitura)…")
            repair_inventory = fetch_board_inventory(token, args.board)
        client = SundayClient(sunday_config_from_test_env())
        sunday_board = BOARD_ALLOWLIST[args.board]
        sunday_snapshots = snapshot_from_live_client(client, [sunday_board])
        snapshot = sunday_snapshots[sunday_board]
        ledger = load_persistent_ledger(args.ledger)
        migrated_ids = {
            str(record["monday_item_id"])
            for record in ledger.values()
            if record.get("monday_board_id") == args.board
            and record.get("migration_status") == "migrated"
        }
        scope_ids = requested_item_ids or frozenset(migrated_ids)
        if args.max_items and requested_item_ids is None and len(scope_ids) > args.max_items:
            scope_ids = frozenset(sorted(scope_ids)[: args.max_items])
        apply_sources = fetch_monday_apply_sources(token, args.board, item_ids=scope_ids)
        audit_completed_at = os.environ.get(
            "MIGRATION_AUDIT_COMPLETED_AT",
            "2026-08-13T01:21:00+00:00",
        )
        try:
            repair_plan = build_repair_plan(
                monday_board_id=args.board,
                sunday_board_id=sunday_board,
                inventory=repair_inventory,
                sunday_snapshot=snapshot,
                apply_sources=apply_sources,
                client=client,
                ledger_records=ledger,
                item_ids=requested_item_ids if requested_item_ids else scope_ids,
                max_items=args.max_items if requested_item_ids is None else None,
                audit_completed_at=audit_completed_at,
            )
        except RepairPlanAbort as exc:
            print(f"ABORT: {exc}")
            return 3
        payload = repair_plan.to_payload()
        Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(f"\nREPAIR PLAN gravado em {args.out}")
        summary = {
            k: payload[k]
            for k in (
                "monday_board_id",
                "sunday_board_id",
                "mode",
                "items_scope",
                "items_to_repair",
                "status_writes",
                "notificacao_link_writes",
                "docs_sac_link_writes",
                "total_link_writes",
                "total_writes",
                "skip_source_empty",
                "skip_already_correct",
                "blocked",
                "gate_ok",
                "gate_detail",
            )
        }
        if args.confirm_writes:
            board_plan = build_board_plan(
                repair_inventory,
                snapshot,
                sunday_board_by_monday_map(),
            )
            try:
                apply_result = apply_repair_plan(
                    plan=repair_plan,
                    client=client,
                    sunday_snapshot=snapshot,
                    board_plan=board_plan,
                    inventory=repair_inventory,
                    apply_sources=apply_sources,
                    fail_fast=True,
                )
            except RepairApplyAbort as exc:
                print(f"ABORT: {exc}")
                return 3
            apply_payload = apply_result.to_payload()
            Path(args.apply_report_out).write_text(
                json.dumps(apply_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"\nREPAIR APPLY concluído; relatório em {args.apply_report_out}")
            summary["repair_apply"] = {
                "status_writes": apply_result.status_writes,
                "link_writes": apply_result.link_writes,
                "skipped": apply_result.skipped,
                "failed": apply_result.failed,
            }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    inventory_holder: dict[str, object] = {"inventory": None}
    plan_holder: dict[str, object] = {"plan": None}
    scoped_context: dict[str, object] = {}

    def _build_scoped_safety(current_inventory, current_plan):
        from classificacao_procons.migration.operation_manifest import (
            attach_scoped_safety_metadata,
        )

        if requested_item_ids is None or client is None or not sunday_snapshots:
            return None
        monday_token = get_api_token_from_env()
        if not monday_token:
            raise ExecutorAbort("MONDAY_API_TOKEN ausente para manifesto escopado.")
        sunday_board = BOARD_ALLOWLIST[args.board]
        sunday_snapshot = sunday_snapshots[sunday_board]
        monday_id_column_id = _find_monday_id_column(sunday_snapshot)
        scoped_items = tuple(
            item for item in current_inventory.items if item.item_id in requested_item_ids
        )
        scoped_inventory = replace(current_inventory, items=scoped_items)
        board_plan = build_board_plan(
            scoped_inventory,
            sunday_snapshot,
            sunday_board_by_monday_map(),
        )
        apply_sources = fetch_monday_apply_sources(
            monday_token,
            args.board,
            item_ids=requested_item_ids,
        )
        if len(apply_sources) != len(requested_item_ids):
            raise ExecutorAbort(
                f"apply_sources={len(apply_sources)} != allowlist={len(requested_item_ids)}.",
            )
        scoped_context["board_plan"] = board_plan
        scoped_context["apply_sources"] = apply_sources
        scoped_context["monday_id_column_id"] = monday_id_column_id
        scoped_context["sunday_snapshot"] = sunday_snapshot
        return attach_scoped_safety_metadata(
            inventory=current_inventory,
            board_plan=board_plan,
            sunday_snapshot=sunday_snapshot,
            apply_sources=apply_sources,
            plan_operations=list(current_plan.operations),
            selected_item_ids=requested_item_ids,
            monday_id_column_id=monday_id_column_id,
            monday_board_id=args.board,
            existing_comment_markers=sunday_comment_markers or None,
        )

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
        current_plan = plan_holder.get("plan")
        if requested_item_ids is not None and client is not None and current_plan is not None:
            return _build_scoped_safety(inventory, current_plan)
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

    monday_id_index = {}
    sunday_comment_markers = {}
    if client is not None and sunday_snapshots:
        monday_id_column_id = _find_monday_id_column(
            sunday_snapshots[BOARD_ALLOWLIST[args.board]],
        )
        monday_id_index = build_sunday_monday_id_index(
            client,
            board_id=BOARD_ALLOWLIST[args.board],
            monday_id_column_id=monday_id_column_id,
        )
        sunday_comment_markers = build_sunday_comment_marker_index(
            client,
            monday_id_index=monday_id_index,
            inventory=inventory,
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
        item_ids=requested_item_ids,
        max_comments=args.max_comments,
        mode=args.mode,
        user_policy=policy,
        persistent_ledger=load_persistent_ledger(args.ledger),
        sunday_monday_id_index=monday_id_index or None,
        sunday_comment_markers=sunday_comment_markers or None,
        sunday_schema_checks=schema_checks,
    )
    plan_holder["plan"] = plan

    if requested_item_ids is not None and client is not None and sunday_snapshots:
        plan.scoped_safety = _build_scoped_safety(inventory, plan)
        if args.max_operations is not None and args.max_writes is not None:
            if args.max_operations != args.max_writes:
                raise ExecutorAbort(
                    "--max-operations e --max-writes divergem; use apenas um.",
                )
        requested_max = args.max_operations if args.max_operations is not None else args.max_writes
        if requested_max is None and plan.scoped_safety is not None:
            plan.max_operations = plan.scoped_safety.accounting.operation_total
        elif requested_max is not None:
            plan.max_operations = requested_max
        from classificacao_procons.migration.executor import _build_gate

        plan.gate = _build_gate(plan, schema_checks)

    Path(args.out).write_text(
        json.dumps(plan.to_payload(), ensure_ascii=False, indent=2), encoding="utf-8",
    )
    payload = plan.to_payload()
    print(f"\nPLAN gravado em {args.out}")
    print(json.dumps({k: payload[k] for k in (
        "monday_board_id", "sunday_board_id", "wave", "mode", "snapshot", "counts",
        "source_updates", "updates_migraveis", "comments_to_create",
        "comments_already_present", "comments_excluded",
        "attachments_to_link", "relations_to_create",
        "relations_unresolved", "gate_ok", "max_operations", "max_writes", "scoped_safety",
        "operation_accounting",
    )}, ensure_ascii=False, indent=2))
    for check in payload["gate"]:
        print(f"  gate[{'OK ' if check['ok'] else 'FAIL'}] {check['check']}: {check['detail']}")

    if args.mode == "plan":
        return 0

    try:
        counts = payload.get("counts", {})
        expected_writable = counts.get("create", 0) + counts.get("resume", 0)
        _validate_plan_payload(
            payload,
            expected_writable=expected_writable,
            allow_already_migrated=counts.get("already_migrated", 0) > 0,
            expected_comments=args.max_comments,
        )
    except ExecutorAbort as exc:
        print(f"\nABORT: {exc}")
        return 3

    if client is None:
        print("ABORT: client Sunday ausente.")
        return 3

    sunday_snapshot = sunday_snapshots[BOARD_ALLOWLIST[args.board]]
    selected_ids = {
        operation.monday_item_id
        for operation in plan.operations
        if operation.action in ("create", "resume")
    }
    scoped_items = tuple(item for item in inventory.items if item.item_id in selected_ids)
    if len(scoped_items) != len(selected_ids):
        print(
            f"ABORT: itens no inventário={len(scoped_items)} != "
            f"allowlist={len(selected_ids)}.",
        )
        return 3
    scoped_inventory = replace(inventory, items=scoped_items)
    board_plan = build_board_plan(
        scoped_inventory,
        sunday_snapshot,
        sunday_board_by_monday_map(),
    )
    monday_token = get_api_token_from_env()
    if not monday_token:
        print("ABORT: MONDAY_API_TOKEN ausente para APPLY.")
        return 2
    apply_sources = fetch_monday_apply_sources(
        monday_token,
        args.board,
        item_ids=selected_ids,
    )
    if len(apply_sources) != len(selected_ids):
        print(
            f"ABORT: apply_sources={len(apply_sources)} != "
            f"allowlist={len(selected_ids)}.",
        )
        return 3

    from classificacao_procons.migration.source_completeness import (
        check_source_completeness_for_sources,
    )

    completeness = check_source_completeness_for_sources(
        inventory=scoped_inventory,
        board_plan=board_plan,
        apply_sources=apply_sources,
        item_ids=selected_ids,
        sunday_snapshot=sunday_snapshot,
    )
    if not completeness.ok:
        print(f"ABORT: source completeness guard: {completeness.detail}")
        return 3

    migration_context = ApplyMigrationContext(
        inventory=scoped_inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources=apply_sources,
        monday_id_column_id=_find_monday_id_column(sunday_snapshot),
        target_group_id=_find_target_group_id(sunday_snapshot),
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
        inventory=scoped_inventory,
        board_plan=board_plan,
        apply_sources=apply_sources,
        monday_id_column_id=migration_context.monday_id_column_id,
        target_group_id=migration_context.target_group_id,
    )

    post_plan = build_execution_plan(
        inventory=inventory_holder["inventory"],  # type: ignore[arg-type]
        report=report,
        wave=args.wave,
        max_items=args.max_items,
        item_ids=requested_item_ids,
        mode="plan",
        user_policy=policy,
        persistent_ledger=load_persistent_ledger(args.ledger),
        sunday_monday_id_index=build_sunday_monday_id_index(
            client,
            board_id=plan.sunday_board_id,
            monday_id_column_id=migration_context.monday_id_column_id,
        ),
        sunday_comment_markers=build_sunday_comment_marker_index(
            client,
            monday_id_index=build_sunday_monday_id_index(
                client,
                board_id=plan.sunday_board_id,
                monday_id_column_id=migration_context.monday_id_column_id,
            ),
            inventory=inventory_holder["inventory"],  # type: ignore[arg-type]
        ),
        sunday_schema_checks=schema_checks,
    )
    post_payload = post_plan.to_payload()

    apply_report = {
        "monday_board_id": args.board,
        "sunday_board_id": plan.sunday_board_id,
        "succeeded": apply_result.succeeded,
        "failed": [
            {"monday_item_id": item_id, "error": err}
            for item_id, err in apply_result.failed
        ],
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
