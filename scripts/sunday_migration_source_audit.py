#!/usr/bin/env python3
"""Auditoria retroativa SOURCE → TARGET dos itens migrados (read-only)."""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict

from classificacao_procons.migration.apply_writer import (
    build_sunday_monday_id_index,
    fetch_monday_apply_sources,
)
from classificacao_procons.migration.executor import load_persistent_ledger, sunday_config_from_test_env
from classificacao_procons.migration.monday_inventory import fetch_board_inventory
from classificacao_procons.migration.source_audit import (
    AUDIT_BOARD_SUNDAY,
    audit_board_migrated_items,
    audit_comments_for_items,
    explain_legacy_field_checker,
    summarize_mapping_coverage,
)
from classificacao_procons.migration.source_completeness import check_source_completeness_for_sources
from classificacao_procons.migration.mappings import build_board_plan, sunday_board_by_monday_map
from classificacao_procons.migration.sunday_snapshot import snapshot_from_live_client
from classificacao_procons.monday.client import get_api_token_from_env
from classificacao_procons.sunday.client import SundayClient

GISLAINNE_FIELDS = (
    "Cancelamento de Assinatura?",
    "Status",
    "Causa 1",
    "Causa 2",
    "Origem",
    "Docs SAC",
    "Observações/Histórico",
    "Prazo Resposta Processo Administrativo",
)


def _find_monday_id_column(snapshot):
    return next(
        column.id
        for column in snapshot.columns
        if column.label.strip().lower() == "monday id"
    )


def _target_group_id(snapshot, name: str = "Itens") -> str:
    matches = [
        group_id
        for group_id, group_name in snapshot.groups.items()
        if group_name.strip().casefold() == name.casefold()
    ]
    return matches[0]


def _fetch_sources_chunked(
    token: str,
    board_id: str,
    item_ids: set[str],
    *,
    chunk_size: int = 5,
) -> dict[str, object]:
    sources: dict[str, object] = {}
    ordered = sorted(item_ids)
    for offset in range(0, len(ordered), chunk_size):
        chunk = set(ordered[offset : offset + chunk_size])
        sources.update(fetch_monday_apply_sources(token, board_id, item_ids=chunk))
    return sources


def _board_metrics_dict(metrics) -> dict[str, object]:
    return {
        "items_audited": metrics.items_audited,
        "items_100_percent_correct": metrics.items_fully_correct,
        "items_100_percent_verified": metrics.items_fully_verified,
        "semantic_resolution_unverified_fields": metrics.semantic_resolution_unverified,
        "items_with_divergence": metrics.items_with_divergence,
        "source_non_empty_fields": metrics.source_non_empty_business_fields,
        "expected_mapped_fields": metrics.expected_mapped_fields,
        "matched": metrics.matched,
        "mismatched": metrics.mismatched,
        "missing_target": metrics.missing_target_values,
        "unmapped_source": metrics.unmapped_source_fields,
        "field_fidelity_rate": round(metrics.field_fidelity_rate, 4),
    }


def _simulate_batch(w1_create_ops, size):
    selected = w1_create_ops[:size]
    comments = sum(op[0] for op in selected)
    attachments = sum(op[2] for op in selected)
    return {
        "items": len(selected),
        "comments": comments,
        "attachments": attachments,
        "blocked": 0,
        "estimated_writes": len(selected) + comments + attachments,
    }


def main() -> int:
    token = get_api_token_from_env()
    if not token:
        print(json.dumps({"error": "MONDAY_API_TOKEN ausente"}))
        return 2

    client = SundayClient(sunday_config_from_test_env())
    ledger = load_persistent_ledger()
    counts = defaultdict(int)
    for record in ledger.values():
        board = record.get("monday_board_id", "")
        if record.get("migration_status") == "migrated":
            counts[board] += 1
    counts["total"] = len(ledger)

    sunday_boards = list(AUDIT_BOARD_SUNDAY.values())
    snapshots = snapshot_from_live_client(client, sunday_boards)

    board_metrics: dict[str, object] = {}
    comment_metrics: dict[str, object] = {}
    mapping_matrices: dict[str, list] = {}
    gislainne: dict[str, object] = {"found": False}
    completeness_current: dict[str, object] = {}

    procons_create_candidates = []

    for monday_board_id, sunday_board_id in AUDIT_BOARD_SUNDAY.items():
        inventory = fetch_board_inventory(token, monday_board_id)
        snapshot = snapshots[sunday_board_id]
        monday_id_col = _find_monday_id_column(snapshot)
        migrated_ids = {
            str(record["monday_item_id"])
            for record in ledger.values()
            if record.get("monday_board_id") == monday_board_id
            and record.get("migration_status") == "migrated"
        }
        sources = _fetch_sources_chunked(token, monday_board_id, migrated_ids)
        metrics = audit_board_migrated_items(
            monday_board_id=monday_board_id,
            inventory=inventory,
            sunday_snapshot=snapshot,
            apply_sources=sources,
            client=client,
            monday_id_column_id=monday_id_col,
            target_group_id=_target_group_id(snapshot),
            ledger_records=ledger,
        )
        board_metrics[monday_board_id] = _board_metrics_dict(metrics)
        mapping_matrices[monday_board_id] = metrics.mapping_matrix

        monday_id_index = build_sunday_monday_id_index(
            client,
            board_id=sunday_board_id,
            monday_id_column_id=monday_id_col,
        )
        comments = audit_comments_for_items(
            inventory=inventory,
            monday_item_ids=migrated_ids,
            sunday_client=client,
            monday_id_index=monday_id_index,
        )
        comment_metrics[monday_board_id] = {
            "source_updates_migraveis": comments.source_updates_migraveis,
            "markers_expected": comments.markers_expected,
            "markers_present": comments.markers_present,
            "missing": comments.missing,
            "duplicates": comments.duplicates,
            "metadata_errors": comments.metadata_errors,
        }

        board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
        completeness = check_source_completeness_for_sources(
            inventory=inventory,
            board_plan=board_plan,
            apply_sources=sources,
            item_ids=migrated_ids,
        )
        completeness_current[monday_board_id] = {
            "ok": completeness.ok,
            "issues": len(completeness.issues),
        }

        if monday_board_id == "4944254220":
            for item in metrics.item_results:
                for row in item.fields:
                    if row.field_name == "name" and row.source_value:
                        if "gislainne" in row.source_value.casefold():
                            gislainne["found"] = True
                            gislainne["monday_item_id"] = item.monday_item_id
                            gislainne["sunday_item_id"] = item.sunday_item_id
                            table = []
                            source = sources[item.monday_item_id]
                            for field_name in GISLAINNE_FIELDS:
                                match_row = next(
                                    (r for r in item.fields if r.field_name == field_name),
                                    None,
                                )
                                monday_val = None
                                for col in inventory.columns:
                                    if col.title == field_name:
                                        monday_val = source.values_by_column_id.get(col.id)
                                        break
                                if monday_val and len(monday_val) > 80:
                                    monday_val = "[preenchido]"
                                sunday_val = (
                                    match_row.actual_value if match_row else None
                                )
                                if isinstance(sunday_val, str) and len(sunday_val) > 80:
                                    sunday_val = "[preenchido]"
                                table.append(
                                    {
                                        "campo": field_name,
                                        "monday": monday_val,
                                        "sunday": sunday_val,
                                        "mapping": (
                                            match_row.mapping_status if match_row else "?"
                                        ),
                                        "resultado": (
                                            match_row.result if match_row else "?"
                                        ),
                                    },
                                )
                            gislainne["table"] = table

            from classificacao_procons.migration.dry_run import run_dry_run
            from classificacao_procons.migration.executor import build_execution_plan
            from classificacao_procons.migration.user_mapping import load_user_mapping_policy

            policy = load_user_mapping_policy()
            report, _, _ = run_dry_run(
                {monday_board_id: inventory},
                snapshots,
                user_policy=policy,
                users_mapped=set(policy.exact_match_ids),
            )
            w1_plan = build_execution_plan(
                inventory=inventory,
                report=report,
                wave=1,
                max_items=9999,
                user_policy=policy,
                persistent_ledger=ledger,
                sunday_monday_id_index=monday_id_index,
            )
            for op in w1_plan.operations:
                if op.action != "create":
                    continue
                if op.attachments_to_link > 0:
                    continue
                if op.subitem_count > 0:
                    continue
                if op.monday_item_id in migrated_ids:
                    continue
                procons_create_candidates.append(
                    (op.comments_to_create, int(op.monday_item_id), op.attachments_to_link),
                )
            procons_create_candidates.sort(key=lambda row: (row[0], row[1]))

    procons_inv = fetch_board_inventory(token, "4944254220")
    from classificacao_procons.migration.dry_run import run_dry_run
    from classificacao_procons.migration.executor import build_execution_plan, snapshot_fingerprint
    from classificacao_procons.migration.user_mapping import load_user_mapping_policy

    policy = load_user_mapping_policy()
    procons_report, _, _ = run_dry_run(
        {"4944254220": procons_inv},
        snapshots,
        user_policy=policy,
        users_mapped=set(policy.exact_match_ids),
    )
    w1_full = build_execution_plan(
        inventory=procons_inv,
        report=procons_report,
        wave=1,
        max_items=9999,
        user_policy=policy,
        persistent_ledger=ledger,
    )
    wc = w1_full.counts()

    classe_b = [row for row in procons_create_candidates if row[0] >= 1]
    classe_c_attach = sum(
        1 for op in w1_full.operations if op.action == "create" and op.attachments_to_link > 0
    )
    comment_values = [row[0] for row in classe_b]

    out = {
        "scope": {
            "kpi": counts["5563754463"],
            "trabalhista": counts["4443297481"],
            "procons": counts["4944254220"],
            "total": counts["total"],
        },
        "kpi": board_metrics["5563754463"],
        "trabalhista": {
            **board_metrics["4443297481"],
            **{
                f"comments_{k}": v
                for k, v in comment_metrics["4443297481"].items()
            },
        },
        "procons": {
            **board_metrics["4944254220"],
            **{
                f"comments_{k}": v
                for k, v in comment_metrics["4944254220"].items()
            },
        },
        "gislainne": gislainne,
        "mapping_coverage": summarize_mapping_coverage(mapping_matrices),
        "global": {
            "items_audited": sum(
                board_metrics[b]["items_audited"] for b in AUDIT_BOARD_SUNDAY
            ),
            "items_100_percent_correct": sum(
                board_metrics[b]["items_100_percent_correct"] for b in AUDIT_BOARD_SUNDAY
            ),
            "items_with_divergence": sum(
                board_metrics[b]["items_with_divergence"] for b in AUDIT_BOARD_SUNDAY
            ),
            "expected_mapped_fields": sum(
                board_metrics[b]["expected_mapped_fields"] for b in AUDIT_BOARD_SUNDAY
            ),
            "matched": sum(board_metrics[b]["matched"] for b in AUDIT_BOARD_SUNDAY),
            "mismatched": sum(board_metrics[b]["mismatched"] for b in AUDIT_BOARD_SUNDAY),
            "missing_target": sum(
                board_metrics[b]["missing_target"] for b in AUDIT_BOARD_SUNDAY
            ),
            "unmapped_source": sum(
                board_metrics[b]["unmapped_source"] for b in AUDIT_BOARD_SUNDAY
            ),
        },
        "legacy_checker": explain_legacy_field_checker(),
        "source_completeness_current_migrated": completeness_current,
        "wave1_procons": {
            "source": len(w1_full.operations),
            "already_migrated": wc.get("already_migrated", 0),
            "create": wc.get("create", 0),
        },
        "simulation": {
            "10": _simulate_batch(classe_b, 10),
            "25": _simulate_batch(classe_b, 25),
            "50": _simulate_batch(classe_b, 50),
            "classe_b_distribution": {
                "items": len(classe_b),
                "comments_total": sum(comment_values),
                "min": min(comment_values) if comment_values else 0,
                "median": statistics.median(comment_values) if comment_values else 0,
                "p75": (
                    statistics.quantiles(comment_values, n=4)[2]
                    if len(comment_values) >= 4
                    else max(comment_values, default=0)
                ),
                "max": max(comment_values) if comment_values else 0,
            },
            "classe_c_with_attachments": classe_c_attach,
        },
        "snapshot_procons": {
            "source": len(procons_inv.items),
            "fingerprint": snapshot_fingerprint(procons_inv),
        },
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
