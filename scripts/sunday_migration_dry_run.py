#!/usr/bin/env python3
"""Dry-run global da migração Monday → Sunday (SOMENTE leitura; nenhuma escrita).

Fluxo:
1. Lê os boards Monday da Onda 1 (live via MONDAY_API_TOKEN ou snapshot JSON);
2. Lê o schema dos boards Sunday de destino (snapshot versionado; live com
   --refresh-sunday usando exclusivamente SUNDAY_API_*_TEST — apenas GETs);
3. Aplica wave + disposição + conservação de source rows;
4. Grava relatório agregado sanitizado.

Uso:
    SUNDAY_API_URL="$SUNDAY_API_URL_TEST" SUNDAY_API_TOKEN="$SUNDAY_API_TOKEN_TEST" \\
        python scripts/sunday_migration_dry_run.py --refresh-sunday --out /tmp/dry-run.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from classificacao_procons.migration.dry_run import default_cutoff, run_dry_run
from classificacao_procons.migration.mappings import (
    WAVE1_DOMAINS,
    sunday_board_by_monday_map,
    validate_group_rules_coverage,
    validate_wave1_targets,
)
from classificacao_procons.migration.monday_inventory import (
    fetch_board_inventory,
    inventory_from_payload,
    inventory_to_payload,
)
from classificacao_procons.migration.sunday_snapshot import (
    load_snapshot_file,
    snapshot_from_live_client,
)
from classificacao_procons.migration.user_mapping import (
    DEFAULT_IDENTITIES_PATH,
    load_user_mapping_policy,
)
from classificacao_procons.monday.client import get_api_token_from_env
from classificacao_procons.sunday.http import SundayConfig

DEFAULT_SUNDAY_SNAPSHOT = "docs/sunday-ws22-schema-snapshot-2026-08-11.json"
WAVE1_SUNDAY_BOARD_IDS = ["72", "77", "82", "83", "84", "85", "86", "87"]


def _sunday_client_from_test_env():
    """Cliente Sunday usando exclusivamente secrets *_TEST (aliases em memória)."""
    from classificacao_procons.sunday import SundayClient

    url = os.environ.get("SUNDAY_API_URL_TEST", "").strip().rstrip("/")
    token = os.environ.get("SUNDAY_API_TOKEN_TEST", "").strip()
    if not url or not token:
        print("ERRO: SUNDAY_API_URL_TEST e SUNDAY_API_TOKEN_TEST são obrigatórios.", file=sys.stderr)
        sys.exit(2)
    return SundayClient(SundayConfig(base_url=url, token=token))


def _load_monday(args) -> tuple[dict, str]:
    if args.monday_snapshot:
        payload = json.loads(Path(args.monday_snapshot).read_text(encoding="utf-8"))
        collected_at = payload.get("collected_at", datetime.now(UTC).isoformat())
        inventories = {
            board_id: inventory_from_payload(board)
            for board_id, board in payload["boards"].items()
        }
        return inventories, collected_at
    token = get_api_token_from_env()
    if not token:
        print("ERRO: MONDAY_API_TOKEN ausente e nenhum --monday-snapshot informado.")
        sys.exit(2)
    inventories = {}
    for board_id, meta in WAVE1_DOMAINS.items():
        print(f"Lendo Monday board {board_id} ({meta['name']})…")
        inventories[board_id] = fetch_board_inventory(token, board_id)
    return inventories, datetime.now(UTC).isoformat()


def _preflight_gates(inventories: dict, user_policy_path: str) -> list[str]:
    failures: list[str] = []
    if validate_wave1_targets():
        failures.append("WAVE1_TARGETS incompleto")
    group_gaps = validate_group_rules_coverage(inventories)
    if group_gaps:
        failures.append(f"GROUP_RULES incompleto: {group_gaps}")
    policy = load_user_mapping_policy(user_policy_path)
    if len(policy.active_unmatched_ids) != 3:
        failures.append(
            f"active_sem_match_sunday deve ter 3 IDs (tem {len(policy.active_unmatched_ids)})",
        )
    if len(policy.exact_match_ids) != 25:
        failures.append(
            f"exact_match deve ter 25 IDs (tem {len(policy.exact_match_ids)})",
        )
    if len(policy.deactivated_ids) != 30:
        failures.append(
            f"deactivated deve ter 30 IDs (tem {len(policy.deactivated_ids)})",
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--monday-snapshot", help="JSON de inventário sanitizado já coletado")
    parser.add_argument("--sunday-snapshot", default=DEFAULT_SUNDAY_SNAPSHOT)
    parser.add_argument(
        "--refresh-sunday",
        action="store_true",
        help="atualiza snapshot Sunday ao vivo (só GETs; exige SUNDAY_API_*_TEST)",
    )
    parser.add_argument("--out", default="/tmp/sunday-migration-dry-run.json")
    parser.add_argument(
        "--dump-monday-inventory",
        help="grava o inventário Monday sanitizado neste caminho (JSON)",
    )
    parser.add_argument(
        "--user-identities",
        default=DEFAULT_IDENTITIES_PATH,
        help="JSON de identidades Monday (hash) com active_sem_match_sunday",
    )
    args = parser.parse_args()

    inventories, monday_collected_at = _load_monday(args)
    gate_failures = _preflight_gates(inventories, args.user_identities)
    if gate_failures:
        print("GATE PRÉ-REFRESH: FAIL")
        for failure in gate_failures:
            print(f"  - {failure}")
        return 1
    print("GATE PRÉ-REFRESH: PASS")

    if args.dump_monday_inventory:
        Path(args.dump_monday_inventory).write_text(
            json.dumps(
                {
                    "collected_at": monday_collected_at,
                    "boards": {
                        board_id: inventory_to_payload(inventory)
                        for board_id, inventory in inventories.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Inventário Monday sanitizado: {args.dump_monday_inventory}")

    if args.refresh_sunday:
        client = _sunday_client_from_test_env()
        snapshots = snapshot_from_live_client(client, WAVE1_SUNDAY_BOARD_IDS)
        print("Snapshot Sunday atualizado ao vivo (somente leitura, 8 boards).")
    else:
        snapshots = load_snapshot_file(args.sunday_snapshot)

    user_policy = load_user_mapping_policy(args.user_identities)
    users_mapped = set(user_policy.exact_match_ids)

    cutoff = default_cutoff()
    output: dict[str, object] = {
        "cutoff": cutoff.isoformat(),
        "monday_snapshot_timestamp": monday_collected_at,
        "monday_snapshot_total": sum(len(inv.items) for inv in inventories.values()),
        "monday_count_by_board": {
            board_id: len(inv.items) for board_id, inv in inventories.items()
        },
        "sunday_board_map": sunday_board_by_monday_map(),
    }
    for scenario in ("estado_atual", "pos_checklist"):
        report, plans, pulled = run_dry_run(
            inventories,
            snapshots,
            cutoff=cutoff,
            users_mapped=users_mapped,
            user_policy=user_policy,
            scenario=scenario,
        )
        output[scenario] = report.to_payload()
        output[f"{scenario}_pull_in_relacoes"] = pulled
        if scenario == "pos_checklist":
            output["planos"] = {
                board_id: {
                    "monday": plan.monday_name,
                    "sunday_board_id": plan.sunday_board_id,
                    "sunday_name": plan.sunday_name,
                    "dominio": plan.domain,
                    "confianca": plan.confidence,
                    "nota": plan.note,
                }
                for board_id, plan in plans.items()
            }

    Path(args.out).write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"\nRelatório do dry-run: {args.out}")
    payload = output["pos_checklist"]
    assert isinstance(payload, dict)
    accounting = payload.get("source_accounting", {})
    print(
        f"conservação: {accounting.get('accounted')}/{accounting.get('source_snapshot_total')} "
        f"({'OK' if accounting.get('conserved') else 'ERRO'})",
    )
    for row in payload.get("board_stats", []):
        print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
