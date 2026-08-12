#!/usr/bin/env python3
"""Fase 2 — dry-run da migração Monday → Sunday (SOMENTE leitura; nenhuma escrita).

Fluxo:
1. Lê os boards Monday da Onda 1 (live via MONDAY_API_TOKEN ou snapshot JSON);
2. Lê o schema dos boards Sunday de destino (snapshot versionado; live com
   --refresh-sunday quando SUNDAY_API_TOKEN existir — apenas GETs);
3. Aplica mappings/recorte e classifica cada item (READY/MANUAL/SKIP/ERROR)
   nos cenários `estado_atual` e `pos_checklist`;
4. Grava relatório agregado sanitizado + snapshot de inventário sanitizado.

Uso:
    python scripts/sunday_migration_dry_run.py --out /tmp/dry-run.json
    python scripts/sunday_migration_dry_run.py --monday-snapshot docs/monday-onda1-*.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from classificacao_procons.migration.dry_run import default_cutoff, run_dry_run
from classificacao_procons.migration.mappings import WAVE1_DOMAINS
from classificacao_procons.migration.monday_inventory import (
    fetch_board_inventory,
    inventory_from_payload,
    inventory_to_payload,
)
from classificacao_procons.migration.sunday_snapshot import (
    load_snapshot_file,
    snapshot_from_live_client,
)
from classificacao_procons.monday.client import get_api_token_from_env

DEFAULT_SUNDAY_SNAPSHOT = "docs/sunday-ws22-schema-snapshot-2026-08-11.json"


def _load_monday(args) -> dict:
    if args.monday_snapshot:
        payload = json.loads(Path(args.monday_snapshot).read_text(encoding="utf-8"))
        return {
            board_id: inventory_from_payload(board)
            for board_id, board in payload["boards"].items()
        }
    token = get_api_token_from_env()
    if not token:
        print("ERRO: MONDAY_API_TOKEN ausente e nenhum --monday-snapshot informado.")
        sys.exit(2)
    inventories = {}
    for board_id, meta in WAVE1_DOMAINS.items():
        print(f"Lendo Monday board {board_id} ({meta['name']})…")
        inventories[board_id] = fetch_board_inventory(token, board_id)
    return inventories


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--monday-snapshot", help="JSON de inventário sanitizado já coletado")
    parser.add_argument("--sunday-snapshot", default=DEFAULT_SUNDAY_SNAPSHOT)
    parser.add_argument(
        "--refresh-sunday",
        action="store_true",
        help="atualiza o snapshot Sunday ao vivo (só GETs; exige SUNDAY_API_TOKEN)",
    )
    parser.add_argument("--out", default="/tmp/sunday-migration-dry-run.json")
    parser.add_argument(
        "--dump-monday-inventory",
        help="grava o inventário Monday sanitizado neste caminho (JSON)",
    )
    parser.add_argument(
        "--users-mapped",
        help="JSON com lista de monday_user_ids já aprovados no de-para (Etapa 6)",
    )
    args = parser.parse_args()

    inventories = _load_monday(args)
    if args.dump_monday_inventory:
        Path(args.dump_monday_inventory).write_text(
            json.dumps(
                {
                    "collected_at": datetime.now(UTC).isoformat(),
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
        from classificacao_procons.sunday import SundayClient

        targets = ["72", "77"]
        snapshots = snapshot_from_live_client(SundayClient(), targets)
        print("Snapshot Sunday atualizado ao vivo (somente leitura).")
    else:
        snapshots = load_snapshot_file(args.sunday_snapshot)

    users_mapped: set[str] = set()
    if args.users_mapped:
        users_mapped = set(json.loads(Path(args.users_mapped).read_text(encoding="utf-8")))

    cutoff = default_cutoff()
    output: dict[str, object] = {"cutoff": cutoff.isoformat()}
    for scenario in ("estado_atual", "pos_checklist"):
        report, plans, pulled = run_dry_run(
            inventories,
            snapshots,
            cutoff=cutoff,
            users_mapped=users_mapped,
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
                    "colunas": [
                        {
                            "monday_column_id": column.monday_column_id,
                            "titulo": column.monday_title,
                            "tipo": column.monday_type,
                            "estrategia": column.strategy,
                            "alvo_sunday": column.sunday_target,
                            "existe_no_destino": column.exists_in_target,
                        }
                        for column in plan.column_plans
                    ],
                    "status_mappings": plan.status_mappings,
                    "relacoes": [
                        {
                            "coluna": relation.monday_column_title,
                            "monday_target_board": relation.monday_target_board_id,
                            "sunday_target_esperado": (
                                relation.expected_sunday_target_board_id
                            ),
                            "source_board_id_configurado": (
                                relation.configured_source_board_id
                            ),
                            "config_ok": relation.config_ok,
                            "nota": relation.note,
                        }
                        for relation in plan.relation_plans
                    ],
                }
                for board_id, plan in plans.items()
            }

    Path(args.out).write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"\nRelatório do dry-run: {args.out}")
    for scenario in ("estado_atual", "pos_checklist"):
        payload = output[scenario]
        print(f"\n== {scenario} ==")
        print(json.dumps(payload["counts"], ensure_ascii=False))
        print(
            f"onda1={payload['onda1_total']}  "
            f"onda2_backfill_obrigatorio={payload['onda2_backfill_obrigatorio']}  "
            f"meta={payload['meta_final']}",
        )
        print("percentuais (onda 1):", json.dumps(payload["percentuais_sobre_onda1"]))
        print("manual por motivo:", json.dumps(payload["manual_por_motivo"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
