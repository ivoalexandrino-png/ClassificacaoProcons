"""Repair PLAN para itens já migrados (idempotente; sem CREATE).

Opera por ledger monday_item_id → sunday_item_id. Default: PLAN sem escrita.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from classificacao_procons.migration.apply_writer import MondayApplySource
from classificacao_procons.migration.mappings import build_board_plan, sunday_board_by_monday_map
from classificacao_procons.migration.models import MondayBoardInventory, SundayBoardSnapshot
from classificacao_procons.migration.source_audit import (
    FieldAuditRow,
    ItemAuditResult,
    audit_item_fields,
)

TemporalClassification = Literal[
    "MIGRATION_DEFECT",
    "POST_MIGRATION_DELTA",
    "INCONCLUSIVE",
]

REPAIRABLE_RESULTS = frozenset(
    {
        "MISSING_TARGET_VALUE",
        "MISMATCH",
        "UNMAPPED_SOURCE_FIELD",
        "TRANSFORMATION_ERROR",
    },
)

FILE_FIELD_NAMES = frozenset({"Notificação Procon", "Docs SAC"})


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def classify_item_temporal(
    *,
    migrated_at: str | None,
    source_snapshot_timestamp: str | None,
    source_updated_at: str | None,
) -> TemporalClassification:
    """Distingue defeito de migração vs alteração posterior no Monday."""
    migrated = _parse_ts(migrated_at)
    snap = _parse_ts(source_snapshot_timestamp)
    updated = _parse_ts(source_updated_at)
    if updated and migrated and updated > migrated:
        return "POST_MIGRATION_DELTA"
    if snap and updated and updated <= snap:
        return "MIGRATION_DEFECT"
    if migrated:
        return "MIGRATION_DEFECT"
    return "INCONCLUSIVE"


@dataclass(frozen=True)
class RepairFieldOperation:
    monday_column_id: str
    field_name: str
    operation: str
    sunday_column_id: str | None
    expected_value: object | None
    current_value: object | None
    source_type: str | None = None
    target_type: str | None = None


@dataclass
class RepairItemPlan:
    monday_item_id: str
    sunday_item_id: str
    fields_correct: int = 0
    fields_to_repair: list[RepairFieldOperation] = field(default_factory=list)
    files_to_link: int = 0
    comments_to_repair: int = 0
    blocked: int = 0
    temporal: TemporalClassification = "INCONCLUSIVE"


@dataclass
class RepairPlan:
    monday_board_id: str
    sunday_board_id: str
    mode: str = "repair"
    items: list[RepairItemPlan] = field(default_factory=list)

    @property
    def items_to_repair(self) -> int:
        return sum(1 for item in self.items if item.fields_to_repair or item.comments_to_repair)

    @property
    def field_writes(self) -> int:
        return sum(
            1
            for item in self.items
            for op in item.fields_to_repair
            if op.operation == "set_value"
        )

    @property
    def file_links(self) -> int:
        return sum(item.files_to_link for item in self.items)

    @property
    def comment_repairs(self) -> int:
        return sum(item.comments_to_repair for item in self.items)

    @property
    def blocked(self) -> int:
        return sum(item.blocked for item in self.items)

    def to_payload(self) -> dict:
        return {
            "monday_board_id": self.monday_board_id,
            "sunday_board_id": self.sunday_board_id,
            "mode": self.mode,
            "items_to_repair": self.items_to_repair,
            "field_writes": self.field_writes,
            "file_links": self.file_links,
            "comment_repairs": self.comment_repairs,
            "blocked": self.blocked,
            "items": [
                {
                    "monday_item_id": item.monday_item_id,
                    "sunday_item_id": item.sunday_item_id,
                    "temporal": item.temporal,
                    "fields_correct": item.fields_correct,
                    "fields_to_repair": [
                        {
                            "monday_column_id": op.monday_column_id,
                            "field_name": op.field_name,
                            "operation": op.operation,
                            "sunday_column_id": op.sunday_column_id,
                            "expected_value": op.expected_value,
                            "current_value": op.current_value,
                            "source_type": op.source_type,
                            "target_type": op.target_type,
                        }
                        for op in item.fields_to_repair
                    ],
                    "files_to_link": item.files_to_link,
                    "comments_to_repair": item.comments_to_repair,
                    "blocked": item.blocked,
                }
                for item in self.items
            ],
        }


class RepairPlanAbort(Exception):
    """Aborta repair quando pré-condição falha (ex.: item ausente no ledger)."""


def _ledger_key(monday_board_id: str, monday_item_id: str) -> str:
    return f"{monday_board_id}:{monday_item_id}"


def _operation_for_field(row: FieldAuditRow) -> str | None:
    if row.field_name in FILE_FIELD_NAMES and row.result == "MISSING_TARGET_VALUE":
        return "link_file"
    if row.result in REPAIRABLE_RESULTS:
        return "set_value"
    return None


def _repair_fields_from_audit(
    audit: ItemAuditResult,
    *,
    field_filter: frozenset[str] | None,
) -> tuple[list[RepairFieldOperation], int, int]:
    operations: list[RepairFieldOperation] = []
    files = 0
    correct = 0
    for row in audit.fields:
        if row.field_name.startswith("__"):
            continue
        if row.result in {"MATCH", "OK_EMPTY", "INTENTIONALLY_NOT_MIGRATED"}:
            correct += 1
            continue
        if field_filter is not None and row.field_name not in field_filter:
            continue
        operation = _operation_for_field(row)
        if operation is None:
            continue
        if operation == "link_file":
            files += 1
        operations.append(
            RepairFieldOperation(
                monday_column_id=row.monday_column_id,
                field_name=row.field_name,
                operation=operation,
                sunday_column_id=None,
                expected_value=row.source_value,
                current_value=row.actual_value,
            ),
        )
    return operations, files, correct


def build_repair_plan(
    *,
    monday_board_id: str,
    sunday_board_id: str,
    inventory: MondayBoardInventory,
    sunday_snapshot: SundayBoardSnapshot,
    apply_sources: dict[str, MondayApplySource],
    client,
    monday_id_column_id: str,
    target_group_id: str,
    ledger_records: dict[str, dict],
    item_ids: frozenset[str] | None = None,
    field_filter: frozenset[str] | None = None,
    max_items: int | None = None,
) -> RepairPlan:
    """Gera PLAN de repair idempotente para itens já migrados."""
    board_plan = build_board_plan(inventory, sunday_snapshot, sunday_board_by_monday_map())
    plan = RepairPlan(monday_board_id=monday_board_id, sunday_board_id=sunday_board_id)
    inventory_by_id = {item.item_id: item for item in inventory.items}

    candidates: list[tuple[str, dict]] = []
    for key, record in sorted(ledger_records.items()):
        if record.get("monday_board_id") != monday_board_id:
            continue
        if record.get("migration_status") != "migrated":
            continue
        monday_item_id = str(record.get("monday_item_id", ""))
        if item_ids is not None and monday_item_id not in item_ids:
            continue
        candidates.append((monday_item_id, record))

    if item_ids is not None:
        missing = item_ids - {mid for mid, _ in candidates}
        if missing:
            raise RepairPlanAbort(
                f"Item(ns) ausente(s) no ledger migrado: {sorted(missing)}",
            )

    if max_items is not None:
        candidates = candidates[:max_items]

    for monday_item_id, record in candidates:
        sunday_item_id = str(record.get("sunday_item_id", ""))
        source = apply_sources.get(monday_item_id)
        if source is None:
            plan.items.append(
                RepairItemPlan(
                    monday_item_id=monday_item_id,
                    sunday_item_id=sunday_item_id,
                    blocked=1,
                    temporal="INCONCLUSIVE",
                ),
            )
            continue

        inv_item = inventory_by_id.get(monday_item_id)
        temporal = classify_item_temporal(
            migrated_at=record.get("migrated_at"),
            source_snapshot_timestamp=record.get("source_snapshot_timestamp"),
            source_updated_at=inv_item.updated_at if inv_item else None,
        )

        audit = audit_item_fields(
            inventory=inventory,
            board_plan=board_plan,
            sunday_snapshot=sunday_snapshot,
            source=source,
            sunday_item_id=sunday_item_id,
            client=client,
            monday_id_column_id=monday_id_column_id,
            target_group_id=target_group_id,
        )
        operations, files, correct = _repair_fields_from_audit(
            audit,
            field_filter=field_filter,
        )
        plan.items.append(
            RepairItemPlan(
                monday_item_id=monday_item_id,
                sunday_item_id=sunday_item_id,
                fields_correct=correct,
                fields_to_repair=operations,
                files_to_link=files,
                temporal=temporal,
            ),
        )

    return plan
