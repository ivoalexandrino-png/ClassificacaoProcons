"""Repair APPLY estritamente limitado aos 6 custom statuses pendentes (scope6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from classificacao_procons.migration.apply_writer import MondayApplySource
from classificacao_procons.migration.column_transforms import (
    StatusResolveError,
    resolve_sunday_custom_status_write_value,
)
from classificacao_procons.migration.mappings import (
    slugify_status_key,
)
from classificacao_procons.migration.models import MondayBoardInventory, SundayBoardSnapshot
from classificacao_procons.migration.repair_plan import should_block_field_for_source_change

AUDIT_COMPLETED_AT = "2026-08-13T01:21:00+00:00"

KPI_BOARD_ID = "5563754463"
KPI_SUNDAY_BOARD_ID = "86"
KPI_STATUS_SUNDAY_COLUMN = "569"
KPI_STATUS_MONDAY_COLUMN = "status_11"

PROCONS_BOARD_ID = "4944254220"
PROCONS_SUNDAY_BOARD_ID = "82"
PROCONS_STATUS_SUNDAY_COLUMN = "611"
PROCONS_STATUS_MONDAY_COLUMN = "status_11"

ALLOWED_SUNDAY_STATUS_COLUMNS = frozenset({KPI_STATUS_SUNDAY_COLUMN, PROCONS_STATUS_SUNDAY_COLUMN})

OperationKind = Literal[
    "status_write",
    "skip_already_correct",
    "blocked",
]


@dataclass(frozen=True)
class Scope6Entry:
    monday_board_id: str
    sunday_board_id: str
    monday_item_id: str
    sunday_item_id: str
    monday_column_id: str
    sunday_column_id: str
    audited_source_value: str
    field_name: str


SCOPE6_ENTRIES: tuple[Scope6Entry, ...] = (
    Scope6Entry(
        monday_board_id=KPI_BOARD_ID,
        sunday_board_id=KPI_SUNDAY_BOARD_ID,
        monday_item_id="5563754498",
        sunday_item_id="7721",
        monday_column_id=KPI_STATUS_MONDAY_COLUMN,
        sunday_column_id=KPI_STATUS_SUNDAY_COLUMN,
        audited_source_value="Em Recurso (Nosso)",
        field_name="Resultado",
    ),
    Scope6Entry(
        monday_board_id=KPI_BOARD_ID,
        sunday_board_id=KPI_SUNDAY_BOARD_ID,
        monday_item_id="5567718660",
        sunday_item_id="7722",
        monday_column_id=KPI_STATUS_MONDAY_COLUMN,
        sunday_column_id=KPI_STATUS_SUNDAY_COLUMN,
        audited_source_value="Em Recurso (Nosso)",
        field_name="Resultado",
    ),
    Scope6Entry(
        monday_board_id=KPI_BOARD_ID,
        sunday_board_id=KPI_SUNDAY_BOARD_ID,
        monday_item_id="5568408706",
        sunday_item_id="7724",
        monday_column_id=KPI_STATUS_MONDAY_COLUMN,
        sunday_column_id=KPI_STATUS_SUNDAY_COLUMN,
        audited_source_value="Em Recurso (Nosso)",
        field_name="Resultado",
    ),
    Scope6Entry(
        monday_board_id=KPI_BOARD_ID,
        sunday_board_id=KPI_SUNDAY_BOARD_ID,
        monday_item_id="5568408560",
        sunday_item_id="7741",
        monday_column_id=KPI_STATUS_MONDAY_COLUMN,
        sunday_column_id=KPI_STATUS_SUNDAY_COLUMN,
        audited_source_value="Acordo",
        field_name="Resultado",
    ),
    Scope6Entry(
        monday_board_id=KPI_BOARD_ID,
        sunday_board_id=KPI_SUNDAY_BOARD_ID,
        monday_item_id="5568414230",
        sunday_item_id="7726",
        monday_column_id=KPI_STATUS_MONDAY_COLUMN,
        sunday_column_id=KPI_STATUS_SUNDAY_COLUMN,
        audited_source_value="Acordo",
        field_name="Resultado",
    ),
    Scope6Entry(
        monday_board_id=PROCONS_BOARD_ID,
        sunday_board_id=PROCONS_SUNDAY_BOARD_ID,
        monday_item_id="11437293298",
        sunday_item_id="7762",
        monday_column_id=PROCONS_STATUS_MONDAY_COLUMN,
        sunday_column_id=PROCONS_STATUS_SUNDAY_COLUMN,
        audited_source_value="Problemas com entrega",
        field_name="Causa 1",
    ),
)


class StatusRepairScope6Abort(Exception):
    """Aborta PLAN/APPLY do repair scope6 (fail-closed)."""


@dataclass(frozen=True)
class Scope6FieldPlan:
    entry: Scope6Entry
    source_value: str
    semantic_key: str
    option_key: str
    option_label: str
    target_current: object | None
    operation: OperationKind
    block_reason: str | None = None


@dataclass
class Scope6RepairPlan:
    items: list[Scope6FieldPlan] = field(default_factory=list)

    @property
    def items_scope(self) -> int:
        return len(self.items)

    @property
    def status_writes(self) -> int:
        return sum(1 for item in self.items if item.operation == "status_write")

    @property
    def skip_already_correct(self) -> int:
        return sum(1 for item in self.items if item.operation == "skip_already_correct")

    @property
    def blocked(self) -> int:
        return sum(1 for item in self.items if item.operation == "blocked")

    @property
    def source_changed(self) -> int:
        return sum(
            1 for item in self.items if item.block_reason == "SOURCE_CHANGED_AFTER_AUDIT"
        )


def _column_options(snapshot: SundayBoardSnapshot, sunday_column_id: str) -> list[dict]:
    for column in snapshot.columns:
        if column.id == sunday_column_id:
            return list((column.settings or {}).get("options", []))
    return []


def _resolve_live_option(
    *,
    snapshot: SundayBoardSnapshot,
    sunday_column_id: str,
    source_value: str,
) -> tuple[str, str, str]:
    options = _column_options(snapshot, sunday_column_id)
    semantic_key = slugify_status_key(source_value)
    try:
        option_key = resolve_sunday_custom_status_write_value(
            column_options=options,
            semantic_key=semantic_key,
            monday_label=source_value,
        )
    except StatusResolveError as exc:
        raise StatusRepairScope6Abort(exc.detail) from exc
    label = next(
        (str(opt.get("label", "")) for opt in options if str(opt.get("key")) == option_key),
        "",
    )
    return semantic_key, option_key, label


def _operation_for_target(*, target_current: object | None, option_key: str) -> OperationKind:
    if target_current is None or str(target_current).strip() == "":
        return "status_write"
    if str(target_current) == option_key:
        return "skip_already_correct"
    return "status_write"


def build_scope6_repair_plan(
    *,
    snapshots: dict[str, SundayBoardSnapshot],
    apply_sources: dict[str, dict[str, MondayApplySource]],
    inventories: dict[str, MondayBoardInventory],
    client,
    audit_completed_at: str = AUDIT_COMPLETED_AT,
) -> Scope6RepairPlan:
    plan = Scope6RepairPlan()
    for entry in SCOPE6_ENTRIES:
        if entry.sunday_column_id not in ALLOWED_SUNDAY_STATUS_COLUMNS:
            raise StatusRepairScope6Abort(
                f"Coluna Sunday {entry.sunday_column_id} fora da allowlist scope6.",
            )
        snapshot = snapshots[entry.sunday_board_id]
        board_sources = apply_sources.get(entry.monday_board_id, {})
        source = board_sources.get(entry.monday_item_id)
        if source is None:
            raise StatusRepairScope6Abort(
                f"Source Monday ausente para item {entry.monday_item_id}.",
            )
        live_source = source.values_by_column_id.get(entry.monday_column_id)
        live_source_text = (live_source or "").strip()
        if not live_source_text:
            raise StatusRepairScope6Abort(
                f"Source vazia para {entry.monday_item_id}/{entry.monday_column_id}.",
            )

        inventory = inventories[entry.monday_board_id]
        inv_item = next(
            (item for item in inventory.items if item.item_id == entry.monday_item_id),
            None,
        )
        updated_at = inv_item.updated_at if inv_item else None
        if should_block_field_for_source_change(
            audit_completed_at=audit_completed_at,
            source_updated_at=updated_at,
            audited_source_value=entry.audited_source_value,
            live_source_value=live_source_text,
        ):
            plan.items.append(
                Scope6FieldPlan(
                    entry=entry,
                    source_value=live_source_text,
                    semantic_key=slugify_status_key(live_source_text),
                    option_key="",
                    option_label="",
                    target_current=client.get_value(entry.sunday_item_id, entry.sunday_column_id),
                    operation="blocked",
                    block_reason="SOURCE_CHANGED_AFTER_AUDIT",
                ),
            )
            continue

        semantic_key, option_key, option_label = _resolve_live_option(
            snapshot=snapshot,
            sunday_column_id=entry.sunday_column_id,
            source_value=live_source_text,
        )
        target_current = client.get_value(entry.sunday_item_id, entry.sunday_column_id)
        plan.items.append(
            Scope6FieldPlan(
                entry=entry,
                source_value=live_source_text,
                semantic_key=semantic_key,
                option_key=option_key,
                option_label=option_label,
                target_current=target_current,
                operation=_operation_for_target(
                    target_current=target_current,
                    option_key=option_key,
                ),
            ),
        )
    return plan


@dataclass(frozen=True)
class Scope6ResolutionCounts:
    resolved: int = 0
    unresolved: int = 0
    ambiguous: int = 0


def count_scope6_resolution(plan: Scope6RepairPlan) -> Scope6ResolutionCounts:
    resolved = 0
    unresolved = 0
    ambiguous = 0
    for item in plan.items:
        if item.operation == "blocked":
            continue
        if item.option_key:
            resolved += 1
        else:
            unresolved += 1
    return Scope6ResolutionCounts(resolved=resolved, unresolved=unresolved, ambiguous=ambiguous)


def validate_scope6_pre_repair_plan(plan: Scope6RepairPlan) -> None:
    resolution = count_scope6_resolution(plan)
    expected = {
        "items_scope": 6,
        "status_writes": 6,
        "skip_already_correct": 0,
        "blocked": 0,
        "resolved": 6,
        "unresolved": 0,
        "ambiguous": 0,
        "source_changed": 0,
    }
    actual = {
        "items_scope": plan.items_scope,
        "status_writes": plan.status_writes,
        "skip_already_correct": plan.skip_already_correct,
        "blocked": plan.blocked,
        "resolved": resolution.resolved,
        "unresolved": resolution.unresolved,
        "ambiguous": resolution.ambiguous,
        "source_changed": plan.source_changed,
    }
    if actual != expected:
        raise StatusRepairScope6Abort(
            f"Pre-repair PLAN divergente: esperado {expected}, obtido {actual}.",
        )


@dataclass
class Scope6ApplyWriteResult:
    monday_item_id: str
    sunday_item_id: str
    sunday_column_id: str
    option_key: str
    applied: bool
    read_back_ok: bool
    error: str | None = None


@dataclass
class Scope6ApplyResult:
    writes_succeeded: int = 0
    writes_failed: int = 0
    writes_not_attempted: int = 0
    write_checks_total: int = 0
    write_checks_ok: int = 0
    write_checks_error: int = 0
    items: list[Scope6ApplyWriteResult] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str | None = None


def apply_scope6_repair_plan(
    *,
    plan: Scope6RepairPlan,
    client,
) -> Scope6ApplyResult:
    result = Scope6ApplyResult()
    write_plans = [item for item in plan.items if item.operation == "status_write"]
    result.writes_not_attempted = plan.skip_already_correct + plan.blocked

    for field_plan in plan.items:
        if field_plan.operation == "blocked":
            result.aborted = True
            result.abort_reason = field_plan.block_reason
            result.writes_not_attempted += len(write_plans)
            return result

    for field_plan in plan.items:
        if field_plan.operation != "status_write":
            continue

        entry = field_plan.entry
        if entry.sunday_column_id not in ALLOWED_SUNDAY_STATUS_COLUMNS:
            result.aborted = True
            result.abort_reason = f"Coluna {entry.sunday_column_id} fora da allowlist."
            result.writes_failed += 1
            remaining = len(write_plans) - result.writes_succeeded - result.writes_failed
            result.writes_not_attempted += remaining
            return result

        write_result = Scope6ApplyWriteResult(
            monday_item_id=entry.monday_item_id,
            sunday_item_id=entry.sunday_item_id,
            sunday_column_id=entry.sunday_column_id,
            option_key=field_plan.option_key,
            applied=False,
            read_back_ok=False,
        )
        result.items.append(write_result)
        result.write_checks_total += 1

        try:
            client.set_custom_value(
                entry.sunday_board_id,
                entry.sunday_item_id,
                entry.sunday_column_id,
                field_plan.option_key,
                verify=True,
            )
            write_result.applied = True
            write_result.read_back_ok = True
            result.writes_succeeded += 1
            result.write_checks_ok += 1
        except Exception as exc:
            write_result.error = str(exc)
            result.writes_failed += 1
            result.write_checks_error += 1
            result.aborted = True
            result.abort_reason = str(exc)
            remaining = len(write_plans) - result.writes_succeeded - result.writes_failed
            result.writes_not_attempted += remaining
            return result

    return result


def count_readback_by_source(plan: Scope6RepairPlan, client) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for field_plan in plan.items:
        key = field_plan.source_value
        bucket = counts.setdefault(key, {"expected": 0, "correct": 0})
        bucket["expected"] += 1
        current = client.get_value(
            field_plan.entry.sunday_item_id,
            field_plan.entry.sunday_column_id,
        )
        if str(current) == field_plan.option_key:
            bucket["correct"] += 1
    return counts
