"""Repair PLAN para itens já migrados (idempotente; sem CREATE).

Opera por ledger monday_item_id → sunday_item_id. Default: PLAN sem escrita.
Procons: allowlist explícita de 3 colunas (609, 598, 605).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from classificacao_procons.migration.apply_writer import MondayApplySource
from classificacao_procons.migration.column_transforms import (
    PROCONS_BOARD_ID,
    PROCONS_CANCELAMENTO_MONDAY_COLUMN,
    PROCONS_CANCELAMENTO_SUNDAY_COLUMN,
    PROCONS_DOCS_SAC_MONDAY_COLUMN,
    PROCONS_DOCS_SAC_SUNDAY_COLUMN,
    PROCONS_NOTIFICACAO_MONDAY_COLUMN,
    PROCONS_NOTIFICACAO_SUNDAY_COLUMN,
    PROCONS_REPAIR_MONDAY_COLUMNS,
    derive_file_to_link_value,
    extract_usable_url,
    get_explicit_column_mapping,
    link_values_equal,
)
from classificacao_procons.migration.mappings import (
    build_board_plan,
    slugify_status_key,
    sunday_board_by_monday_map,
)
from classificacao_procons.migration.models import MondayBoardInventory, SundayBoardSnapshot

TemporalClassification = Literal[
    "MIGRATION_DEFECT",
    "POST_MIGRATION_DELTA",
    "INCONCLUSIVE",
]

FieldBlockReason = Literal[
    "SOURCE_CHANGED_AFTER_AUDIT",
    "TRANSFORMATION_ERROR",
    "SOURCE_UNAVAILABLE",
]

OperationKind = Literal[
    "status_write",
    "link_column_write",
    "skip_already_correct",
    "skip_source_empty",
    "blocked",
]


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


def should_block_field_for_source_change(
    *,
    audit_completed_at: str | None,
    source_updated_at: str | None,
    audited_source_value: str | None,
    live_source_value: str | None,
) -> bool:
    """Bloqueia repair se source divergiu do valor auditado."""
    if audited_source_value is None:
        return False
    audited = audited_source_value.strip()
    live = (live_source_value or "").strip()
    if audited != live:
        return True
    audit_ts = _parse_ts(audit_completed_at)
    updated_ts = _parse_ts(source_updated_at)
    return bool(audit_ts and updated_ts and updated_ts > audit_ts and audited != live)


@dataclass(frozen=True)
class RepairFieldPlan:
    monday_column_id: str
    field_name: str
    operation: OperationKind
    sunday_column_id: str
    link_source_present: bool = False
    link_target_column: str | None = None
    link_write_required: bool = False
    expected_value: object | None = None
    current_value: object | None = None
    block_reason: FieldBlockReason | None = None


@dataclass
class RepairItemPlan:
    monday_item_id: str
    sunday_item_id: str
    temporal: TemporalClassification = "INCONCLUSIVE"
    cancelamento_write: bool = False
    notificacao_link_write: bool = False
    docs_sac_link_write: bool = False
    skip_source_empty: int = 0
    skip_already_correct: int = 0
    blocked: int = 0
    fields: list[RepairFieldPlan] = field(default_factory=list)

    @property
    def writes(self) -> int:
        return int(self.cancelamento_write) + int(self.notificacao_link_write) + int(
            self.docs_sac_link_write,
        )

    @property
    def has_work(self) -> bool:
        return self.writes > 0


@dataclass
class RepairPlan:
    monday_board_id: str
    sunday_board_id: str
    mode: str = "repair"
    items: list[RepairItemPlan] = field(default_factory=list)

    @property
    def items_scope(self) -> int:
        return len(self.items)

    @property
    def items_to_repair(self) -> int:
        return sum(1 for item in self.items if item.has_work)

    @property
    def status_writes(self) -> int:
        return sum(1 for item in self.items if item.cancelamento_write)

    @property
    def notificacao_link_writes(self) -> int:
        return sum(1 for item in self.items if item.notificacao_link_write)

    @property
    def docs_sac_link_writes(self) -> int:
        return sum(1 for item in self.items if item.docs_sac_link_write)

    @property
    def total_link_writes(self) -> int:
        return self.notificacao_link_writes + self.docs_sac_link_writes

    @property
    def total_writes(self) -> int:
        return self.status_writes + self.total_link_writes

    @property
    def skip_source_empty(self) -> int:
        return sum(item.skip_source_empty for item in self.items)

    @property
    def skip_already_correct(self) -> int:
        return sum(item.skip_already_correct for item in self.items)

    @property
    def blocked(self) -> int:
        return sum(item.blocked for item in self.items)

    def to_payload(self) -> dict:
        gate_ok, gate_detail = evaluate_repair_gate(self)
        return {
            "monday_board_id": self.monday_board_id,
            "sunday_board_id": self.sunday_board_id,
            "mode": self.mode,
            "items_scope": self.items_scope,
            "items_to_repair": self.items_to_repair,
            "status_writes": self.status_writes,
            "notificacao_link_writes": self.notificacao_link_writes,
            "docs_sac_link_writes": self.docs_sac_link_writes,
            "total_link_writes": self.total_link_writes,
            "total_writes": self.total_writes,
            "skip_source_empty": self.skip_source_empty,
            "skip_already_correct": self.skip_already_correct,
            "blocked": self.blocked,
            "gate_ok": gate_ok,
            "gate_detail": gate_detail,
            "items": [
                {
                    "monday_item_id": item.monday_item_id,
                    "sunday_item_id": item.sunday_item_id,
                    "temporal": item.temporal,
                    "writes": item.writes,
                    "cancelamento_write": item.cancelamento_write,
                    "notificacao_link_write": item.notificacao_link_write,
                    "docs_sac_link_write": item.docs_sac_link_write,
                    "skip_source_empty": item.skip_source_empty,
                    "skip_already_correct": item.skip_already_correct,
                    "blocked": item.blocked,
                    "fields": [
                        {
                            "monday_column_id": field.monday_column_id,
                            "field_name": field.field_name,
                            "operation": field.operation,
                            "sunday_column_id": field.sunday_column_id,
                            "link_source_present": field.link_source_present,
                            "link_target_column": field.link_target_column,
                            "link_write_required": field.link_write_required,
                            "block_reason": field.block_reason,
                        }
                        for field in item.fields
                    ],
                }
                for item in self.items
            ],
        }


class RepairPlanAbort(Exception):
    """Aborta repair quando pré-condição falha (ex.: item ausente no ledger)."""


def evaluate_repair_gate(plan: RepairPlan) -> tuple[bool, str]:
    """Gate fail-closed: BLOCKED reprova; SKIP_* não reprova."""
    if plan.blocked > 0:
        return False, f"{plan.blocked} campo(s) BLOCKED — repair APPLY não autorizado"
    if any(not item.fields and item.blocked for item in plan.items):
        return False, "item sem source Monday resolvida"
    return True, "ledger ok; mapping conhecido; sem BLOCKED; writes na allowlist"


def _status_key_for_label(board_plan, monday_column_id: str, label: str) -> str | None:
    status_map = board_plan.status_mappings.get(monday_column_id, {})
    key = status_map.get(label)
    if key is None and label not in status_map:
        key = slugify_status_key(label)
    return key


def _plan_repair_field(
    *,
    monday_column_id: str,
    field_name: str,
    sunday_column_id: str,
    source_text: str | None,
    current_value: object,
    board_plan,
    audit_completed_at: str | None,
    source_updated_at: str | None,
    audited_source_value: str | None,
    kind: Literal["status", "file_to_link"],
    link_display_text: str | None = None,
) -> RepairFieldPlan:
    live_source = (source_text or "").strip()
    if should_block_field_for_source_change(
        audit_completed_at=audit_completed_at,
        source_updated_at=source_updated_at,
        audited_source_value=audited_source_value,
        live_source_value=live_source or None,
    ):
        return RepairFieldPlan(
            monday_column_id=monday_column_id,
            field_name=field_name,
            operation="blocked",
            sunday_column_id=sunday_column_id,
            block_reason="SOURCE_CHANGED_AFTER_AUDIT",
        )

    if kind == "status":
        if not live_source:
            return RepairFieldPlan(
                monday_column_id=monday_column_id,
                field_name=field_name,
                operation="skip_source_empty",
                sunday_column_id=sunday_column_id,
            )
        expected = _status_key_for_label(board_plan, monday_column_id, live_source)
        if expected is None:
            return RepairFieldPlan(
                monday_column_id=monday_column_id,
                field_name=field_name,
                operation="blocked",
                sunday_column_id=sunday_column_id,
                block_reason="TRANSFORMATION_ERROR",
            )
        if expected == current_value or str(expected) == str(current_value):
            return RepairFieldPlan(
                monday_column_id=monday_column_id,
                field_name=field_name,
                operation="skip_already_correct",
                sunday_column_id=sunday_column_id,
                expected_value=expected,
                current_value=current_value,
            )
        return RepairFieldPlan(
            monday_column_id=monday_column_id,
            field_name=field_name,
            operation="status_write",
            sunday_column_id=sunday_column_id,
            expected_value=expected,
            current_value=current_value,
        )

    url = extract_usable_url(live_source)
    link_present = url is not None
    if not link_present:
        return RepairFieldPlan(
            monday_column_id=monday_column_id,
            field_name=field_name,
            operation="skip_source_empty",
            sunday_column_id=sunday_column_id,
            link_source_present=False,
            link_target_column=sunday_column_id,
            link_write_required=False,
        )
    expected = derive_file_to_link_value(
        source_text=live_source,
        display_text=link_display_text or field_name,
    )
    if expected is None:
        return RepairFieldPlan(
            monday_column_id=monday_column_id,
            field_name=field_name,
            operation="blocked",
            sunday_column_id=sunday_column_id,
            link_source_present=True,
            link_target_column=sunday_column_id,
            block_reason="TRANSFORMATION_ERROR",
        )
    if link_values_equal(expected, current_value):
        return RepairFieldPlan(
            monday_column_id=monday_column_id,
            field_name=field_name,
            operation="skip_already_correct",
            sunday_column_id=sunday_column_id,
            link_source_present=True,
            link_target_column=sunday_column_id,
            link_write_required=False,
            expected_value=expected,
            current_value=current_value,
        )
    return RepairFieldPlan(
        monday_column_id=monday_column_id,
        field_name=field_name,
        operation="link_column_write",
        sunday_column_id=sunday_column_id,
        link_source_present=True,
        link_target_column=sunday_column_id,
        link_write_required=True,
        expected_value=expected,
        current_value=current_value,
    )


def build_repair_plan(
    *,
    monday_board_id: str,
    sunday_board_id: str,
    inventory: MondayBoardInventory,
    sunday_snapshot: SundayBoardSnapshot,
    apply_sources: dict[str, MondayApplySource],
    client,
    ledger_records: dict[str, dict],
    item_ids: frozenset[str] | None = None,
    max_items: int | None = None,
    audit_completed_at: str | None = None,
    audit_source_values: dict[str, dict[str, str]] | None = None,
) -> RepairPlan:
    """Gera PLAN de repair idempotente para itens já migrados (Procons allowlist)."""
    if monday_board_id != PROCONS_BOARD_ID:
        raise RepairPlanAbort(
            f"Repair allowlist explícita só implementada para Procons ({PROCONS_BOARD_ID}).",
        )

    board_plan = build_board_plan(inventory, sunday_snapshot, sunday_board_by_monday_map())
    plan = RepairPlan(monday_board_id=monday_board_id, sunday_board_id=sunday_board_id)
    inventory_by_id = {item.item_id: item for item in inventory.items}
    columns_by_id = {column.id: column for column in inventory.columns}

    candidates: list[tuple[str, dict]] = []
    for _key, record in sorted(ledger_records.items()):
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

    scoped = candidates
    if max_items is not None and item_ids is None:
        scoped = scoped[:max_items]

    repair_columns = (
        (PROCONS_CANCELAMENTO_MONDAY_COLUMN, PROCONS_CANCELAMENTO_SUNDAY_COLUMN, "status"),
        (PROCONS_NOTIFICACAO_MONDAY_COLUMN, PROCONS_NOTIFICACAO_SUNDAY_COLUMN, "file_to_link"),
        (PROCONS_DOCS_SAC_MONDAY_COLUMN, PROCONS_DOCS_SAC_SUNDAY_COLUMN, "file_to_link"),
    )

    for monday_item_id, record in scoped:
        sunday_item_id = str(record.get("sunday_item_id", ""))
        source = apply_sources.get(monday_item_id)
        item_plan = RepairItemPlan(
            monday_item_id=monday_item_id,
            sunday_item_id=sunday_item_id,
        )

        if source is None:
            item_plan.blocked = len(PROCONS_REPAIR_MONDAY_COLUMNS)
            for column_id in PROCONS_REPAIR_MONDAY_COLUMNS:
                column = columns_by_id.get(column_id)
                item_plan.fields.append(
                    RepairFieldPlan(
                        monday_column_id=column_id,
                        field_name=column.title if column else column_id,
                        operation="blocked",
                        sunday_column_id="",
                        block_reason="SOURCE_UNAVAILABLE",
                    ),
                )
            plan.items.append(item_plan)
            continue

        inv_item = inventory_by_id.get(monday_item_id)
        item_plan.temporal = classify_item_temporal(
            migrated_at=record.get("migrated_at"),
            source_snapshot_timestamp=record.get("source_snapshot_timestamp"),
            source_updated_at=inv_item.updated_at if inv_item else None,
        )

        audited_item = (audit_source_values or {}).get(monday_item_id, {})
        updated_at = inv_item.updated_at if inv_item else None

        for monday_col_id, sunday_col_id, kind in repair_columns:
            column = columns_by_id.get(monday_col_id)
            if column is None:
                continue
            explicit = get_explicit_column_mapping(monday_board_id, monday_col_id)
            source_text = source.values_by_column_id.get(monday_col_id)
            current = client.get_value(sunday_item_id, sunday_col_id)
            field_plan = _plan_repair_field(
                monday_column_id=monday_col_id,
                field_name=column.title,
                sunday_column_id=sunday_col_id,
                source_text=source_text,
                current_value=current,
                board_plan=board_plan,
                audit_completed_at=audit_completed_at,
                source_updated_at=updated_at,
                audited_source_value=audited_item.get(monday_col_id),
                kind=kind,  # type: ignore[arg-type]
                link_display_text=explicit.link_display_text if explicit else None,
            )
            item_plan.fields.append(field_plan)

            if field_plan.operation == "skip_already_correct":
                item_plan.skip_already_correct += 1
            elif field_plan.operation == "skip_source_empty":
                item_plan.skip_source_empty += 1
            elif field_plan.operation == "blocked":
                item_plan.blocked += 1
            elif field_plan.operation == "status_write":
                item_plan.cancelamento_write = True
            elif field_plan.operation == "link_column_write":
                if monday_col_id == PROCONS_NOTIFICACAO_MONDAY_COLUMN:
                    item_plan.notificacao_link_write = True
                elif monday_col_id == PROCONS_DOCS_SAC_MONDAY_COLUMN:
                    item_plan.docs_sac_link_write = True

        plan.items.append(item_plan)

    return plan
