#!/usr/bin/env python3
"""Executor Fase 3 — PLAN (default, zero escrita) e APPLY (futuro, fail-closed).

PLAN do piloto KPI:

    python scripts/sunday_migration_execute.py \
        --board 5563754463 --wave 1 --mode plan --max-items 31

APPLY nunca roda sem: --mode apply + --confirm-writes + env
SUNDAY_MIGRATION_ALLOW_APPLY=1 + gate 100% OK + snapshot revalidado.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from classificacao_procons.migration.dry_run import run_dry_run
from classificacao_procons.migration.executor import (
    BOARD_ALLOWLIST,
    ExecutorAbort,
    build_execution_plan,
    build_sunday_schema_checks,
    load_persistent_ledger,
    sunday_config_from_test_env,
)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", required=True, help="monday_board_id (allowlist)")
    parser.add_argument("--wave", required=True, type=int, choices=(1, 2))
    parser.add_argument("--mode", default="plan", choices=("plan", "apply"))
    parser.add_argument("--max-items", required=True, type=int)
    parser.add_argument("--monday-snapshot", help="inventário sanitizado (JSON)")
    parser.add_argument("--sunday-snapshot", default=DEFAULT_SUNDAY_SNAPSHOT)
    parser.add_argument("--refresh-sunday", action="store_true")
    parser.add_argument("--ledger", default="data/monday-sunday-map.json")
    parser.add_argument("--out", default="/tmp/sunday-migration-plan.json")
    parser.add_argument(
        "--confirm-writes",
        action="store_true",
        help="obrigatório (junto com env) para qualquer APPLY futuro",
    )
    args = parser.parse_args()

    if args.board not in BOARD_ALLOWLIST:
        print(f"ABORT: board {args.board} fora da allowlist {sorted(BOARD_ALLOWLIST)}.")
        return 2

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

    schema_checks = []
    sunday_snapshots = {}
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
        sunday_schema_checks=schema_checks,
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

    if args.mode == "apply":
        try:
            raise ExecutorAbort(
                "APPLY não executado: esta fase é somente PLAN "
                "(proteções: --confirm-writes + SUNDAY_MIGRATION_ALLOW_APPLY=1 "
                "+ gate OK + snapshot revalidado).",
            )
        except ExecutorAbort as exc:
            print(f"\nABORT: {exc}")
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
