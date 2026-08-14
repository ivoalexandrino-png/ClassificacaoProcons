"""Manifesto canônico de operações Monday→Sunday (PLAN/APPLY compartilhado).

Gera fingerprints escopados, schema fingerprint e contabilidade idêntica ao
``apply_writer`` sem executar writes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from classificacao_procons.migration.apply_writer import (
    MondayApplySource,
    is_file_to_link_mapping,
)
from classificacao_procons.migration.column_transforms import StatusResolveError
from classificacao_procons.migration.executor import (
    PlannedOperation,
    comment_idempotency_marker,
    snapshot_fingerprint,
)
from classificacao_procons.migration.models import (
    BoardPlan,
    MondayBoardInventory,
    SundayBoardSnapshot,
    SundayColumnSnapshot,
)

ManifestKind = Literal[
    "CREATE_ITEM",
    "SYSTEM_FIELD_WRITE",
    "CUSTOM_FIELD_WRITE",
    "STATUS_WRITE",
    "COMMENT_CREATE",
    "LINK_WRITE",
    "ATTACHMENT",
    "RELATION",
    "SUBITEM",
    "LEDGER_ENTRY",
]


@dataclass(frozen=True)
class ManifestOperation:
    kind: ManifestKind
    op_id: str
    monday_item_id: str
    monday_column_id: str | None = None
    sunday_column_id: str | None = None
    update_id: str | None = None
    field_name: str | None = None


@dataclass
class OperationAccounting:
    item_creates: int = 0
    system_fields: int = 0
    custom_fields_total: int = 0
    status_within_custom_fields: int = 0
    non_status_custom_fields: int = 0
    comments: int = 0
    links: int = 0
    attachments: int = 0
    relations: int = 0
    subitems: int = 0
    ledger_entries: int = 0

    @property
    def sunday_write_operations(self) -> int:
        return (
            self.item_creates
            + self.system_fields
            + self.custom_fields_total
            + self.comments
            + self.links
            + self.attachments
            + self.relations
            + self.subitems
        )

    @property
    def technical_operations(self) -> int:
        return self.sunday_write_operations + self.ledger_entries

    @property
    def operation_total(self) -> int:
        """Total fail-closed sem double-count de status (subset informativo)."""
        return self.technical_operations

    def as_dict(self) -> dict[str, int]:
        return {
            "item_creates": self.item_creates,
            "system_fields": self.system_fields,
            "custom_fields_total": self.custom_fields_total,
            "status_within_custom_fields": self.status_within_custom_fields,
            "non_status_custom_fields": self.non_status_custom_fields,
            "comments": self.comments,
            "links": self.links,
            "attachments": self.attachments,
            "relations": self.relations,
            "subitems": self.subitems,
            "ledger_entries": self.ledger_entries,
            "sunday_write_operations": self.sunday_write_operations,
            "technical_operations": self.technical_operations,
            "operation_total": self.operation_total,
        }


@dataclass(frozen=True)
class ScopedSafetyMetadata:
    board_global_fingerprint: str
    board_source_total: int
    selected_item_ids: tuple[str, ...]
    selected_source_fingerprint: str
    migration_schema_fingerprint: str
    operation_manifest_hash: str
    accounting: OperationAccounting
    manifest_operations: tuple[ManifestOperation, ...] = ()
    board_drift_outside_scope: bool = False
    scope_safe_despite_global_drift: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "board_global_fingerprint": self.board_global_fingerprint,
            "board_source_total": self.board_source_total,
            "selected_item_ids": list(self.selected_item_ids),
            "selected_source_fingerprint": self.selected_source_fingerprint,
            "migration_schema_fingerprint": self.migration_schema_fingerprint,
            "operation_manifest_hash": self.operation_manifest_hash,
            "accounting": self.accounting.as_dict(),
            "manifest_operation_count": len(self.manifest_operations),
            "board_drift_outside_scope": self.board_drift_outside_scope,
            "scope_safe_despite_global_drift": self.scope_safe_despite_global_drift,
        }


def board_global_fingerprint(inventory: MondayBoardInventory) -> str:
    """Fingerprint legado de todo o board (drift global)."""
    return snapshot_fingerprint(inventory)


def _hash_basis(basis: object) -> str:
    return hashlib.sha256(
        json.dumps(basis, sort_keys=True, ensure_ascii=True).encode(),
    ).hexdigest()[:24]


def _migration_values_basis(
    *,
    inventory: MondayBoardInventory,
    board_plan: BoardPlan,
    apply_source: MondayApplySource,
) -> tuple[tuple[str, str | None], ...]:
    column_plans = {plan.monday_column_id: plan for plan in board_plan.column_plans}
    basis: list[tuple[str, str | None]] = []
    for monday_column in inventory.columns:
        if monday_column.type in {
            "name", "subtasks", "mirror", "lookup", "item_id",
            "creation_log", "last_updated", "people", "file",
            "board_relation", "formula",
        }:
            continue
        plan_column = column_plans.get(monday_column.id)
        if plan_column is None or not plan_column.sunday_column_id:
            continue
        text = apply_source.values_by_column_id.get(monday_column.id)
        if not (text or "").strip():
            continue
        basis.append((monday_column.id, text.strip()))
    return tuple(sorted(basis))


def selected_source_fingerprint(
    *,
    inventory: MondayBoardInventory,
    board_plan: BoardPlan,
    apply_sources: dict[str, MondayApplySource],
    item_ids: frozenset[str],
    existing_comment_markers: dict[str, set[str]] | None = None,
) -> str:
    """Fingerprint determinístico apenas dos itens autorizados."""
    items_by_id = {item.item_id: item for item in inventory.items}
    markers = existing_comment_markers or {}
    basis: list[tuple[object, ...]] = []
    for item_id in sorted(item_ids):
        item = items_by_id.get(item_id)
        source = apply_sources.get(item_id)
        if item is None or source is None:
            basis.append((item_id, "MISSING"))
            continue
        migratable_updates = tuple(
            sorted(
                (
                    update.update_id,
                    update.created_at or "",
                    update.classification,
                    update.is_migratable,
                    update.exclusion_reason or "",
                )
                for update in item.update_diagnostics
                if update.is_migratable
            ),
        )
        relation_basis = tuple(
            sorted(
                (column_id, tuple(sorted(targets)))
                for column_id, targets in sorted(item.relation_targets.items())
            ),
        )
        basis.append(
            (
                item_id,
                item.updated_at or "",
                item.group_id or "",
                _migration_values_basis(
                    inventory=inventory,
                    board_plan=board_plan,
                    apply_source=source,
                ),
                migratable_updates,
                item.file_count,
                item.file_bytes,
                relation_basis,
                item.subitem_count,
                tuple(sorted(markers.get(item_id, set()))),
            ),
        )
    return _hash_basis(basis)


def migration_schema_fingerprint(
    *,
    inventory: MondayBoardInventory,
    board_plan: BoardPlan,
    sunday_snapshot: SundayBoardSnapshot,
) -> str:
    """Configuração Sunday/Monday que afeta writes do lote."""
    monday_basis = tuple(
        sorted(
            (
                plan.monday_column_id,
                plan.monday_type,
                plan.sunday_column_id,
                plan.strategy,
                plan.sunday_target,
            )
            for plan in board_plan.column_plans
            if plan.sunday_column_id
        ),
    )
    sunday_columns_basis: list[tuple[object, ...]] = []
    for column in sunday_snapshot.columns:
        options_basis = tuple(
            sorted(
                (str(option.get("key", "")), str(option.get("label", "")))
                for option in (column.settings or {}).get("options", [])
            ),
        )
        sunday_columns_basis.append(
            (
                column.id,
                column.key,
                column.type,
                column.is_system,
                options_basis,
            ),
        )
    groups_basis = tuple(sorted(sunday_snapshot.groups.items()))
    relations_basis = tuple(
        sorted(
            (
                rel.monday_column_id,
                rel.monday_target_board_id,
                rel.sunday_column_id,
                rel.expected_sunday_target_board_id,
                rel.config_ok,
            )
            for rel in board_plan.relation_plans
        ),
    )
    basis = (
        board_plan.monday_board_id,
        board_plan.sunday_board_id,
        monday_basis,
        tuple(sorted(sunday_columns_basis)),
        groups_basis,
        relations_basis,
        tuple(sorted(board_plan.status_mappings.items())),
    )
    return _hash_basis(basis)


def operation_manifest_hash(operations: tuple[ManifestOperation, ...]) -> str:
    basis = tuple((op.kind, op.op_id) for op in sorted(operations, key=lambda row: row.op_id))
    return _hash_basis(basis)


def summarize_manifest_accounting(
    operations: tuple[ManifestOperation, ...],
) -> OperationAccounting:
    accounting = OperationAccounting()
    for op in operations:
        if op.kind == "CREATE_ITEM":
            accounting.item_creates += 1
        elif op.kind == "SYSTEM_FIELD_WRITE":
            accounting.system_fields += 1
        elif op.kind == "CUSTOM_FIELD_WRITE":
            accounting.custom_fields_total += 1
            accounting.non_status_custom_fields += 1
        elif op.kind == "STATUS_WRITE":
            accounting.custom_fields_total += 1
            accounting.status_within_custom_fields += 1
        elif op.kind == "COMMENT_CREATE":
            accounting.comments += 1
        elif op.kind == "LINK_WRITE":
            accounting.links += 1
        elif op.kind == "ATTACHMENT":
            accounting.attachments += 1
        elif op.kind == "RELATION":
            accounting.relations += 1
        elif op.kind == "SUBITEM":
            accounting.subitems += 1
        elif op.kind == "LEDGER_ENTRY":
            accounting.ledger_entries += 1
    return accounting


def _column_plan_by_monday_id(board_plan: BoardPlan) -> dict[str, object]:
    return {plan.monday_column_id: plan for plan in board_plan.column_plans}


def _sunday_column_by_id(snapshot: SundayBoardSnapshot) -> dict[str, SundayColumnSnapshot]:
    return {column.id: column for column in snapshot.columns}


def _planned_custom_writes(
    *,
    monday_board_id: str,
    monday_item_id: str,
    inventory: MondayBoardInventory,
    board_plan: BoardPlan,
    sunday_snapshot: SundayBoardSnapshot,
    apply_source: MondayApplySource,
    monday_id_column_id: str,
) -> list[ManifestOperation]:
    from classificacao_procons.migration.apply_writer import (
        _sunday_value_for_monday_column,
        _value_for_custom_column_write,
    )

    operations: list[ManifestOperation] = []
    operations.append(
        ManifestOperation(
            kind="CUSTOM_FIELD_WRITE",
            op_id=f"item:{monday_item_id}:custom:{monday_id_column_id}",
            monday_item_id=monday_item_id,
            monday_column_id=monday_id_column_id,
            sunday_column_id=monday_id_column_id,
            field_name="monday_id",
        ),
    )
    column_plans = _column_plan_by_monday_id(board_plan)
    sunday_columns = _sunday_column_by_id(sunday_snapshot)
    for monday_column in inventory.columns:
        if is_file_to_link_mapping(monday_board_id, monday_column.id):
            plan_column = column_plans.get(monday_column.id)
            if plan_column is None or not plan_column.exists_in_target:
                continue
            sunday_column_id = plan_column.sunday_column_id
            if not sunday_column_id:
                continue
            sunday_column = sunday_columns.get(sunday_column_id)
            if sunday_column is None or sunday_column.is_system:
                continue
            text = apply_source.values_by_column_id.get(monday_column.id)
            value = _sunday_value_for_monday_column(
                monday_column=monday_column,
                text=text,
                board_plan=board_plan,
            )
            if value is None:
                continue
            operations.append(
                ManifestOperation(
                    kind="LINK_WRITE",
                    op_id=f"item:{monday_item_id}:link:{monday_column.id}",
                    monday_item_id=monday_item_id,
                    monday_column_id=monday_column.id,
                    sunday_column_id=sunday_column_id,
                ),
            )
            continue
        if monday_column.type in {
            "name", "subtasks", "mirror", "lookup", "item_id",
            "creation_log", "last_updated", "people", "file",
            "board_relation", "formula",
        }:
            continue
        plan_column = column_plans.get(monday_column.id)
        if plan_column is None or not plan_column.exists_in_target:
            continue
        if plan_column.strategy not in {"direto", "transformacao", "configurar_manualmente"}:
            continue
        sunday_column_id = plan_column.sunday_column_id
        if not sunday_column_id:
            continue
        sunday_column = sunday_columns.get(sunday_column_id)
        if sunday_column is None or sunday_column.is_system:
            continue
        text = apply_source.values_by_column_id.get(monday_column.id)
        try:
            _value_for_custom_column_write(
                monday_column=monday_column,
                source_text=text,
                board_plan=board_plan,
                sunday_column=sunday_column,
            )
        except (StatusResolveError, ValueError):
            continue
        kind: ManifestKind = (
            "STATUS_WRITE" if monday_column.type == "status" else "CUSTOM_FIELD_WRITE"
        )
        segment = "status" if kind == "STATUS_WRITE" else "custom"
        operations.append(
            ManifestOperation(
                kind=kind,
                op_id=f"item:{monday_item_id}:{segment}:{monday_column.id}",
                monday_item_id=monday_item_id,
                monday_column_id=monday_column.id,
                sunday_column_id=sunday_column_id,
            ),
        )
    return operations


def plan_item_manifest_operations(
    *,
    monday_board_id: str,
    operation: PlannedOperation,
    inventory: MondayBoardInventory,
    board_plan: BoardPlan,
    sunday_snapshot: SundayBoardSnapshot,
    apply_source: MondayApplySource,
    monday_id_column_id: str,
    existing_comment_markers: set[str] | None = None,
) -> tuple[ManifestOperation, ...]:
    """Manifesto canônico de um item CREATE/resume (sem PII no hash)."""
    item_id = operation.monday_item_id
    markers = existing_comment_markers or set()
    operations: list[ManifestOperation] = []

    if operation.action == "create":
        operations.append(
            ManifestOperation(
                kind="CREATE_ITEM",
                op_id=f"item:{item_id}:create",
                monday_item_id=item_id,
            ),
        )
        operations.extend(
            _planned_custom_writes(
                monday_board_id=monday_board_id,
                monday_item_id=item_id,
                inventory=inventory,
                board_plan=board_plan,
                sunday_snapshot=sunday_snapshot,
                apply_source=apply_source,
                monday_id_column_id=monday_id_column_id,
            ),
        )
        if apply_source.name:
            operations.append(
                ManifestOperation(
                    kind="SYSTEM_FIELD_WRITE",
                    op_id=f"item:{item_id}:system:name",
                    monday_item_id=item_id,
                    field_name="name",
                ),
            )
        operations.append(
            ManifestOperation(
                kind="SYSTEM_FIELD_WRITE",
                op_id=f"item:{item_id}:system:status_sistema",
                monday_item_id=item_id,
                field_name="status_sistema",
            ),
        )

    migratable = tuple(
        update for update in operation.update_diagnostics if update.is_migratable
    )
    for update in migratable:
        marker = comment_idempotency_marker(item_id, update.update_id)
        if marker in markers:
            continue
        operations.append(
            ManifestOperation(
                kind="COMMENT_CREATE",
                op_id=f"item:{item_id}:comment:{update.update_id}",
                monday_item_id=item_id,
                update_id=update.update_id,
            ),
        )

    if operation.action in ("create", "resume", "adopt"):
        operations.append(
            ManifestOperation(
                kind="LEDGER_ENTRY",
                op_id=f"ledger:{monday_board_id}:{item_id}",
                monday_item_id=item_id,
            ),
        )

    if operation.attachments_to_link:
        for index in range(operation.attachments_to_link):
            operations.append(
                ManifestOperation(
                    kind="ATTACHMENT",
                    op_id=f"item:{item_id}:attachment:{index}",
                    monday_item_id=item_id,
                ),
            )
    if operation.subitem_count:
        for index in range(operation.subitem_count):
            operations.append(
                ManifestOperation(
                    kind="SUBITEM",
                    op_id=f"item:{item_id}:subitem:{index}",
                    monday_item_id=item_id,
                ),
            )

    return tuple(sorted(operations, key=lambda row: row.op_id))


def build_scoped_operation_manifest(
    *,
    plan_operations: list[PlannedOperation],
    inventory: MondayBoardInventory,
    board_plan: BoardPlan,
    sunday_snapshot: SundayBoardSnapshot,
    apply_sources: dict[str, MondayApplySource],
    monday_id_column_id: str,
    monday_board_id: str,
    existing_comment_markers: dict[str, set[str]] | None = None,
) -> tuple[ManifestOperation, ...]:
    manifest: list[ManifestOperation] = []
    markers = existing_comment_markers or {}
    for operation in plan_operations:
        if operation.action not in ("create", "resume"):
            continue
        source = apply_sources.get(operation.monday_item_id)
        if source is None:
            continue
        manifest.extend(
            plan_item_manifest_operations(
                monday_board_id=monday_board_id,
                operation=operation,
                inventory=inventory,
                board_plan=board_plan,
                sunday_snapshot=sunday_snapshot,
                apply_source=source,
                monday_id_column_id=monday_id_column_id,
                existing_comment_markers=markers.get(operation.monday_item_id, set()),
            ),
        )
    return tuple(sorted(manifest, key=lambda row: row.op_id))


def attach_scoped_safety_metadata(
    *,
    inventory: MondayBoardInventory,
    board_plan: BoardPlan,
    sunday_snapshot: SundayBoardSnapshot,
    apply_sources: dict[str, MondayApplySource],
    plan_operations: list[PlannedOperation],
    selected_item_ids: frozenset[str],
    monday_id_column_id: str,
    monday_board_id: str,
    approved_board_global_fingerprint: str | None = None,
    existing_comment_markers: dict[str, set[str]] | None = None,
) -> ScopedSafetyMetadata:
    """Calcula fingerprints + manifesto para lote com --item-ids explícitos."""
    global_fp = board_global_fingerprint(inventory)
    selected_fp = selected_source_fingerprint(
        inventory=inventory,
        board_plan=board_plan,
        apply_sources=apply_sources,
        item_ids=selected_item_ids,
        existing_comment_markers=existing_comment_markers,
    )
    schema_fp = migration_schema_fingerprint(
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
    )
    manifest_ops = build_scoped_operation_manifest(
        plan_operations=plan_operations,
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources=apply_sources,
        monday_id_column_id=monday_id_column_id,
        monday_board_id=monday_board_id,
        existing_comment_markers=existing_comment_markers,
    )
    manifest_hash = operation_manifest_hash(manifest_ops)
    accounting = summarize_manifest_accounting(manifest_ops)
    board_drift = (
        approved_board_global_fingerprint is not None
        and global_fp != approved_board_global_fingerprint
    )
    return ScopedSafetyMetadata(
        board_global_fingerprint=global_fp,
        board_source_total=len(inventory.items),
        selected_item_ids=tuple(sorted(selected_item_ids)),
        selected_source_fingerprint=selected_fp,
        migration_schema_fingerprint=schema_fp,
        operation_manifest_hash=manifest_hash,
        accounting=accounting,
        manifest_operations=manifest_ops,
        board_drift_outside_scope=board_drift,
        scope_safe_despite_global_drift=not board_drift,
    )


def compare_scoped_drift(
    *,
    approved: ScopedSafetyMetadata,
    current: ScopedSafetyMetadata,
) -> tuple[bool, bool, bool, bool]:
    """Retorna (board_global_changed, selected_scope_changed, schema_changed, scope_safe)."""
    board_changed = (
        current.board_global_fingerprint != approved.board_global_fingerprint
        or current.board_source_total != approved.board_source_total
    )
    selected_changed = (
        current.selected_source_fingerprint != approved.selected_source_fingerprint
    )
    schema_changed = (
        current.migration_schema_fingerprint != approved.migration_schema_fingerprint
    )
    scope_safe = (
        not selected_changed
        and not schema_changed
        and current.operation_manifest_hash == approved.operation_manifest_hash
    )
    return board_changed, selected_changed, schema_changed, scope_safe


def validate_scoped_apply_fingerprints(
    *,
    approved: ScopedSafetyMetadata,
    current: ScopedSafetyMetadata,
) -> list[str]:
    """Retorna lista de motivos de abort (vazia = OK)."""
    failures: list[str] = []
    if current.selected_source_fingerprint != approved.selected_source_fingerprint:
        failures.append("selected_source_fingerprint divergente")
    if current.migration_schema_fingerprint != approved.migration_schema_fingerprint:
        failures.append("migration_schema_fingerprint divergente")
    if current.operation_manifest_hash != approved.operation_manifest_hash:
        failures.append("operation_manifest_hash divergente")
    if current.accounting.operation_total != approved.accounting.operation_total:
        failures.append("operation_total divergente")
    return failures
