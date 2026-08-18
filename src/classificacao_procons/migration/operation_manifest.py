"""Manifesto canônico de operações Monday→Sunday (PLAN/APPLY compartilhado).

Accounting Model A — kinds mutuamente exclusivos no manifesto:

- CREATE_ITEM
- SYSTEM_FIELD_WRITE
- CUSTOM_FIELD_WRITE (text/date/people/monday_id/outros; **não** status/link)
- STATUS_WRITE
- LINK_WRITE
- COMMENT_CREATE
- ATTACHMENT / RELATION / SUBITEM
- LEDGER_ENTRY

``operation_total`` soma cada operação uma única vez.
``all_custom_column_writes`` = custom_other + status + link (métrica derivada).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from classificacao_procons.migration.apply_writer import (
    MondayApplySource,
    MondayUpdateSource,
    derive_system_status_key,
    format_monday_id_column_value,
    format_monday_update_comment,
    is_file_to_link_mapping,
)
from classificacao_procons.migration.column_transforms import (
    PROCONS_DOCS_SAC_MONDAY_COLUMN,
    PROCONS_NOTIFICACAO_MONDAY_COLUMN,
    StatusResolveError,
)
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

MIGRATION_RUNTIME_PACKAGE = "src/classificacao_procons/migration"
MIGRATION_RUNTIME_CLI = "scripts/sunday_migration_execute.py"


def migration_runtime_module_paths(*, repo_root: Path | None = None) -> tuple[str, ...]:
    """Todos os .py runtime do pacote migration + CLI (ordenados, fail-closed)."""
    root = repo_root or Path(__file__).resolve().parents[3]
    paths: list[str] = []
    package_root = root / MIGRATION_RUNTIME_PACKAGE
    for path in sorted(package_root.rglob("*.py")):
        paths.append(path.relative_to(root).as_posix())
    cli_path = root / MIGRATION_RUNTIME_CLI
    if cli_path.is_file():
        cli_relative = cli_path.relative_to(root).as_posix()
        if cli_relative not in paths:
            paths.append(cli_relative)
    return tuple(paths)


MIGRATION_RUNTIME_MODULE_PATHS = migration_runtime_module_paths()


def _migration_module_entries(
    *,
    repo_root: Path,
    module_bytes: dict[str, bytes] | None = None,
) -> list[dict[str, str]]:
    overrides = module_bytes or {}
    entries: list[dict[str, str]] = []
    for relative_path in migration_runtime_module_paths(repo_root=repo_root):
        content = overrides.get(relative_path, (repo_root / relative_path).read_bytes())
        entries.append(
            {
                "path": relative_path,
                "digest": hashlib.sha256(content).hexdigest(),
            },
        )
    return entries


@dataclass(frozen=True)
class ManifestOperation:
    kind: ManifestKind
    op_id: str
    monday_item_id: str
    payload_digest: str
    monday_column_id: str | None = None
    sunday_column_id: str | None = None
    update_id: str | None = None
    field_name: str | None = None


@dataclass
class OperationAccounting:
    """Contagens mutuamente exclusivas (Model A)."""

    item_creates: int = 0
    system_writes: int = 0
    custom_other_writes: int = 0
    status_writes: int = 0
    link_writes: int = 0
    comments: int = 0
    attachments: int = 0
    relations: int = 0
    subitems: int = 0
    ledger_operations: int = 0
    asset_downloads: int = 0
    storage_uploads: int = 0
    storage_adopts: int = 0
    attachment_link_writes: int = 0

    @property
    def all_custom_column_writes(self) -> int:
        return self.custom_other_writes + self.status_writes + self.link_writes

    @property
    def sunday_write_operations(self) -> int:
        return (
            self.item_creates
            + self.system_writes
            + self.custom_other_writes
            + self.status_writes
            + self.link_writes
            + self.comments
            + self.attachments
            + self.relations
            + self.subitems
        )

    @property
    def operation_total(self) -> int:
        return (
            self.sunday_write_operations
            + self.ledger_operations
            + self.storage_uploads
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "item_creates": self.item_creates,
            "system_writes": self.system_writes,
            "custom_other_writes": self.custom_other_writes,
            "status_writes": self.status_writes,
            "link_writes": self.link_writes,
            "comments": self.comments,
            "attachments": self.attachments,
            "relations": self.relations,
            "subitems": self.subitems,
            "asset_downloads": self.asset_downloads,
            "storage_uploads": self.storage_uploads,
            "storage_adopts": self.storage_adopts,
            "attachment_link_writes": self.attachment_link_writes,
            "sunday_write_operations": self.sunday_write_operations,
            "ledger_operations": self.ledger_operations,
            "operation_total": self.operation_total,
            "all_custom_column_writes": self.all_custom_column_writes,
        }


@dataclass
class CustomWriteBreakdown:
    monday_id: int = 0
    status: int = 0
    text: int = 0
    date: int = 0
    people: int = 0
    link: int = 0
    outros: int = 0

    @property
    def total(self) -> int:
        return (
            self.monday_id
            + self.status
            + self.text
            + self.date
            + self.people
            + self.link
            + self.outros
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "monday_id": self.monday_id,
            "status": self.status,
            "text": self.text,
            "date": self.date,
            "people": self.people,
            "link": self.link,
            "outros": self.outros,
            "total": self.total,
        }


@dataclass
class LinkScopeBreakdown:
    notificacao_procon: int = 0
    docs_sac: int = 0
    outros: int = 0

    @property
    def link_writes(self) -> int:
        return self.notificacao_procon + self.docs_sac + self.outros

    def as_dict(self) -> dict[str, int]:
        return {
            "notificacao_procon": self.notificacao_procon,
            "docs_sac": self.docs_sac,
            "outros": self.outros,
            "link_writes": self.link_writes,
            "binary_attachments": 0,
            "uploads": 0,
        }


@dataclass(frozen=True)
class ScopedSafetyMetadata:
    board_global_fingerprint: str
    board_source_total: int
    selected_item_ids: tuple[str, ...]
    selected_source_fingerprint: str
    migration_schema_fingerprint: str
    operation_manifest_hash_v2: str
    code_revision: str
    accounting: OperationAccounting
    manifest_operations: tuple[ManifestOperation, ...] = ()
    custom_breakdown: CustomWriteBreakdown | None = None
    link_scope: LinkScopeBreakdown | None = None
    board_drift_outside_scope: bool = False
    scope_safe_despite_global_drift: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "board_global_fingerprint": self.board_global_fingerprint,
            "board_source_total": self.board_source_total,
            "selected_item_ids": list(self.selected_item_ids),
            "selected_source_fingerprint": self.selected_source_fingerprint,
            "migration_schema_fingerprint": self.migration_schema_fingerprint,
            "operation_manifest_hash_v2": self.operation_manifest_hash_v2,
            "code_revision": self.code_revision,
            "accounting": self.accounting.as_dict(),
            "custom_breakdown": (
                self.custom_breakdown.as_dict() if self.custom_breakdown else None
            ),
            "link_scope": self.link_scope.as_dict() if self.link_scope else None,
            "manifest_operation_count": len(self.manifest_operations),
            "board_drift_outside_scope": self.board_drift_outside_scope,
            "scope_safe_despite_global_drift": self.scope_safe_despite_global_drift,
        }


def board_global_fingerprint(inventory: MondayBoardInventory) -> str:
    """Fingerprint legado de todo o board (drift global)."""
    return snapshot_fingerprint(inventory)


def _hash_basis(basis: object) -> str:
    return hashlib.sha256(
        json.dumps(basis, sort_keys=True, ensure_ascii=True, default=str).encode(),
    ).hexdigest()[:24]


def payload_digest(payload: object) -> str:
    """Digest canônico do payload esperado (sem expor conteúdo em logs)."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str).encode(),
    ).hexdigest()[:24]


def migration_code_revision(*, repo_root: Path | None = None) -> str:
    """Identidade determinística da engine de migração (digest recursivo, não git SHA).

    Compromete recursivamente todo ``src/classificacao_procons/migration/**/*.py``
    mais ``scripts/sunday_migration_execute.py``. Novo/removido/alterado módulo
    runtime invalida approvals anteriores.
    """
    root = repo_root or Path(__file__).resolve().parents[3]
    return _hash_basis(_migration_module_entries(repo_root=root))


def migration_code_revision_for_module_bytes(
    *,
    repo_root: Path,
    module_bytes: dict[str, bytes],
) -> str:
    """Test helper: revision with selective module content overrides."""
    return _hash_basis(_migration_module_entries(repo_root=repo_root, module_bytes=module_bytes))


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
    assets_by_item: dict[str, tuple[object, ...]] | None = None,
) -> str:
    """Fingerprint determinístico apenas dos itens autorizados."""
    from classificacao_procons.migration.monday_asset_metadata import assets_fingerprint_basis

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
        if assets_by_item is not None:
            asset_basis = assets_fingerprint_basis(assets_by_item, item_ids=frozenset({item_id}))[0]
        else:
            asset_basis = (item.file_count, item.file_bytes)
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
                asset_basis,
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


def operation_manifest_hash_v1(operations: tuple[ManifestOperation, ...]) -> str:
    """Hash legado (kind + op_id apenas) — não usar para approval."""
    basis = tuple((op.kind, op.op_id) for op in sorted(operations, key=lambda row: row.op_id))
    return _hash_basis(basis)


def operation_manifest_hash_v2(operations: tuple[ManifestOperation, ...]) -> str:
    """Hash de approval: identidade + payload esperado por operação."""
    basis = tuple(
        (op.kind, op.op_id, op.payload_digest)
        for op in sorted(operations, key=lambda row: row.op_id)
    )
    return _hash_basis(basis)


def summarize_manifest_accounting(
    operations: tuple[ManifestOperation, ...],
) -> OperationAccounting:
    accounting = OperationAccounting()
    for op in operations:
        if op.kind == "CREATE_ITEM":
            accounting.item_creates += 1
        elif op.kind == "SYSTEM_FIELD_WRITE":
            accounting.system_writes += 1
        elif op.kind == "CUSTOM_FIELD_WRITE":
            accounting.custom_other_writes += 1
        elif op.kind == "STATUS_WRITE":
            accounting.status_writes += 1
        elif op.kind == "LINK_WRITE":
            accounting.link_writes += 1
        elif op.kind == "COMMENT_CREATE":
            accounting.comments += 1
        elif op.kind == "ATTACHMENT":
            accounting.attachments += 1
            accounting.attachment_link_writes += 1
            accounting.storage_uploads += 1
        elif op.kind == "RELATION":
            accounting.relations += 1
        elif op.kind == "SUBITEM":
            accounting.subitems += 1
        elif op.kind == "LEDGER_ENTRY":
            accounting.ledger_operations += 1
    return accounting


def summarize_custom_write_breakdown(
    operations: tuple[ManifestOperation, ...],
    *,
    inventory: MondayBoardInventory,
) -> CustomWriteBreakdown:
    columns = {column.id: column for column in inventory.columns}
    breakdown = CustomWriteBreakdown()
    for op in operations:
        if op.kind == "STATUS_WRITE":
            breakdown.status += 1
        elif op.kind == "LINK_WRITE":
            breakdown.link += 1
        elif op.kind == "CUSTOM_FIELD_WRITE":
            if op.field_name == "monday_id":
                breakdown.monday_id += 1
            else:
                column = columns.get(op.monday_column_id or "")
                if column is None:
                    breakdown.outros += 1
                elif column.type in {"text", "long_text", "link", "email", "location"}:
                    breakdown.text += 1
                elif column.type == "date":
                    breakdown.date += 1
                elif column.type == "people":
                    breakdown.people += 1
                elif column.type == "numbers":
                    breakdown.outros += 1
                else:
                    breakdown.outros += 1
    return breakdown


def summarize_link_scope(
    operations: tuple[ManifestOperation, ...],
) -> LinkScopeBreakdown:
    scope = LinkScopeBreakdown()
    for op in operations:
        if op.kind != "LINK_WRITE":
            continue
        column_id = op.monday_column_id or ""
        if column_id == PROCONS_NOTIFICACAO_MONDAY_COLUMN:
            scope.notificacao_procon += 1
        elif column_id == PROCONS_DOCS_SAC_MONDAY_COLUMN:
            scope.docs_sac += 1
        else:
            scope.outros += 1
    return scope


def _column_plan_by_monday_id(board_plan: BoardPlan) -> dict[str, object]:
    return {plan.monday_column_id: plan for plan in board_plan.column_plans}


def _sunday_column_by_id(snapshot: SundayBoardSnapshot) -> dict[str, SundayColumnSnapshot]:
    return {column.id: column for column in snapshot.columns}


def _update_source_by_id(
    apply_source: MondayApplySource,
) -> dict[str, MondayUpdateSource]:
    return {update.update_id: update for update in apply_source.updates}


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
    monday_id_value = format_monday_id_column_value(monday_board_id, monday_item_id)
    operations.append(
        ManifestOperation(
            kind="CUSTOM_FIELD_WRITE",
            op_id=f"item:{monday_item_id}:custom:{monday_id_column_id}",
            monday_item_id=monday_item_id,
            monday_column_id=monday_id_column_id,
            sunday_column_id=monday_id_column_id,
            field_name="monday_id",
            payload_digest=payload_digest(
                {
                    "sunday_column_id": monday_id_column_id,
                    "value": monday_id_value,
                },
            ),
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
                    payload_digest=payload_digest(
                        {
                            "sunday_column_id": sunday_column_id,
                            "link": value,
                        },
                    ),
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
            value = _value_for_custom_column_write(
                monday_column=monday_column,
                source_text=text,
                board_plan=board_plan,
                sunday_column=sunday_column,
            )
        except (StatusResolveError, ValueError):
            continue
        if monday_column.type == "status":
            operations.append(
                ManifestOperation(
                    kind="STATUS_WRITE",
                    op_id=f"item:{monday_item_id}:status:{monday_column.id}",
                    monday_item_id=monday_item_id,
                    monday_column_id=monday_column.id,
                    sunday_column_id=sunday_column_id,
                    payload_digest=payload_digest(
                        {
                            "sunday_column_id": sunday_column_id,
                            "option_key": value,
                        },
                    ),
                ),
            )
        else:
            operations.append(
                ManifestOperation(
                    kind="CUSTOM_FIELD_WRITE",
                    op_id=f"item:{monday_item_id}:custom:{monday_column.id}",
                    monday_item_id=monday_item_id,
                    monday_column_id=monday_column.id,
                    sunday_column_id=sunday_column_id,
                    payload_digest=payload_digest(
                        {
                            "sunday_column_id": sunday_column_id,
                            "value": value,
                        },
                    ),
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
    item_assets: tuple[object, ...] | None = None,
) -> tuple[ManifestOperation, ...]:
    """Manifesto canônico de um item CREATE/resume (sem PII no hash/log)."""
    item_id = operation.monday_item_id
    markers = existing_comment_markers or set()
    updates_by_id = _update_source_by_id(apply_source)
    operations: list[ManifestOperation] = []

    if operation.action == "create":
        operations.append(
            ManifestOperation(
                kind="CREATE_ITEM",
                op_id=f"item:{item_id}:create",
                monday_item_id=item_id,
                payload_digest=payload_digest(
                    {
                        "sunday_board_id": board_plan.sunday_board_id,
                        "target_group": operation.target_group,
                        "group_action": operation.group_action,
                        "initial_name_set": bool(apply_source.name),
                        "status_sistema": derive_system_status_key(inventory, item_id),
                    },
                ),
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
                    payload_digest=payload_digest(
                        {"field": "name", "value_digest": payload_digest(apply_source.name)},
                    ),
                ),
            )
        operations.append(
            ManifestOperation(
                kind="SYSTEM_FIELD_WRITE",
                op_id=f"item:{item_id}:system:status_sistema",
                monday_item_id=item_id,
                field_name="status_sistema",
                payload_digest=payload_digest(
                    {
                        "field": "status_sistema",
                        "value": derive_system_status_key(inventory, item_id),
                    },
                ),
            ),
        )

    migratable = tuple(
        update for update in operation.update_diagnostics if update.is_migratable
    )
    for update in migratable:
        marker = comment_idempotency_marker(item_id, update.update_id)
        if marker in markers:
            continue
        update_source = updates_by_id.get(update.update_id)
        if update_source is None:
            comment_payload = {
                "update_id": update.update_id,
                "content_digest": payload_digest(
                    {"update_id": update.update_id, "missing_source": True},
                ),
            }
        else:
            comment_payload = {
                "update_id": update.update_id,
                "content_digest": payload_digest(
                    format_monday_update_comment(item_id, update_source),
                ),
            }
        operations.append(
            ManifestOperation(
                kind="COMMENT_CREATE",
                op_id=f"item:{item_id}:comment:{update.update_id}",
                monday_item_id=item_id,
                update_id=update.update_id,
                payload_digest=payload_digest(comment_payload),
            ),
        )

    if operation.action in ("create", "resume", "adopt"):
        operations.append(
            ManifestOperation(
                kind="LEDGER_ENTRY",
                op_id=f"ledger:{monday_board_id}:{item_id}",
                monday_item_id=item_id,
                payload_digest=payload_digest(
                    {
                        "monday_board_id": monday_board_id,
                        "monday_item_id": item_id,
                        "sunday_board_id": board_plan.sunday_board_id,
                        "wave": operation.wave,
                        "disposition": operation.disposition,
                    },
                ),
            ),
        )

    if item_assets:
        from classificacao_procons.migration.asset_pipeline import attachment_payload_digest

        for asset in item_assets:
            asset_id = getattr(asset, "asset_id", None)
            if not asset_id:
                continue
            operations.append(
                ManifestOperation(
                    kind="ATTACHMENT",
                    op_id=f"item:{item_id}:asset:{asset_id}",
                    monday_item_id=item_id,
                    payload_digest=attachment_payload_digest(asset),
                ),
            )
    elif operation.attachments_to_link:
        for index in range(operation.attachments_to_link):
            operations.append(
                ManifestOperation(
                    kind="ATTACHMENT",
                    op_id=f"item:{item_id}:attachment:{index}",
                    monday_item_id=item_id,
                    payload_digest=payload_digest({"attachment_index": index}),
                ),
            )
    if operation.subitem_count:
        for index in range(operation.subitem_count):
            operations.append(
                ManifestOperation(
                    kind="SUBITEM",
                    op_id=f"item:{item_id}:subitem:{index}",
                    monday_item_id=item_id,
                    payload_digest=payload_digest({"subitem_index": index}),
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
    assets_by_item: dict[str, tuple[object, ...]] | None = None,
) -> tuple[ManifestOperation, ...]:
    manifest: list[ManifestOperation] = []
    markers = existing_comment_markers or {}
    for operation in plan_operations:
        if operation.action not in ("create", "resume"):
            continue
        source = apply_sources.get(operation.monday_item_id)
        if source is None:
            continue
        item_assets = assets_by_item.get(operation.monday_item_id) if assets_by_item else None
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
                item_assets=item_assets,
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
    repo_root: Path | None = None,
    assets_by_item: dict[str, tuple[object, ...]] | None = None,
) -> ScopedSafetyMetadata:
    """Calcula fingerprints + manifesto v2 para lote com --item-ids explícitos."""
    global_fp = board_global_fingerprint(inventory)
    selected_fp = selected_source_fingerprint(
        inventory=inventory,
        board_plan=board_plan,
        apply_sources=apply_sources,
        item_ids=selected_item_ids,
        existing_comment_markers=existing_comment_markers,
        assets_by_item=assets_by_item,
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
        assets_by_item=assets_by_item,
    )
    manifest_hash_v2 = operation_manifest_hash_v2(manifest_ops)
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
        operation_manifest_hash_v2=manifest_hash_v2,
        code_revision=migration_code_revision(repo_root=repo_root),
        accounting=accounting,
        manifest_operations=manifest_ops,
        custom_breakdown=summarize_custom_write_breakdown(
            manifest_ops,
            inventory=inventory,
        ),
        link_scope=summarize_link_scope(manifest_ops),
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
        and current.operation_manifest_hash_v2 == approved.operation_manifest_hash_v2
        and current.code_revision == approved.code_revision
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
    if current.operation_manifest_hash_v2 != approved.operation_manifest_hash_v2:
        failures.append("operation_manifest_hash_v2 divergente")
    if current.code_revision != approved.code_revision:
        failures.append("code_revision divergente")
    if current.accounting.operation_total != approved.accounting.operation_total:
        failures.append("operation_total divergente")
    return failures
