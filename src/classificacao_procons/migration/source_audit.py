"""Auditoria retroativa SOURCE → TARGET (Monday → Sunday).

Compara valores derivados da source Monday com o Sunday real migrado.
Não usa o PLAN como fonte da verdade — apenas reutiliza as mesmas regras
de transformação do apply_writer para derivar expected values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from classificacao_procons.migration.apply_writer import (
    MondayApplySource,
    derive_system_status_key,
    format_monday_id_column_value,
)
from classificacao_procons.migration.column_transforms import (
    StatusResolveError,
    derive_file_to_link_value,
    get_explicit_column_mapping,
    is_file_to_link_mapping,
    link_values_equal,
    resolve_sunday_custom_status_option,
)
from classificacao_procons.migration.executor import (
    comment_idempotency_marker,
    load_persistent_ledger,
)
from classificacao_procons.migration.mappings import (
    build_board_plan,
    slugify_status_key,
    sunday_board_by_monday_map,
)
from classificacao_procons.migration.models import (
    BoardPlan,
    ColumnPlan,
    MondayBoardInventory,
    MondayColumnInfo,
    SundayBoardSnapshot,
)

MappingStatus = Literal[
    "MAPPED_DIRECT",
    "MAPPED_TRANSFORM",
    "INTENTIONALLY_NOT_MIGRATED",
    "SOURCE_ONLY_TECHNICAL",
    "UNMAPPED",
]

FieldResult = Literal[
    "MATCH",
    "MISMATCH",
    "MISSING_TARGET_VALUE",
    "UNMAPPED_SOURCE_FIELD",
    "TRANSFORMATION_ERROR",
    "INTENTIONALLY_NOT_MIGRATED",
    "OK_EMPTY",
    "SEMANTIC_RESOLUTION_UNVERIFIED",
]

SOURCE_ONLY_TECHNICAL_TYPES = frozenset(
    {
        "item_id",
        "creation_log",
        "last_updated",
        "subtasks",
        "mirror",
        "lookup",
    },
)

APPLY_WRITER_SKIP_TYPES = frozenset(
    {
        "name",
        "subtasks",
        "mirror",
        "lookup",
        "item_id",
        "creation_log",
        "last_updated",
        "people",
        "file",
        "board_relation",
        "formula",
    },
)

AUDIT_BOARD_SUNDAY = {
    "5563754463": "86",
    "4443297481": "85",
    "4944254220": "82",
}


def _normalize_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def classify_mapping_status(column_plan: ColumnPlan) -> tuple[MappingStatus, str | None]:
    if column_plan.monday_type in SOURCE_ONLY_TECHNICAL_TYPES:
        return "SOURCE_ONLY_TECHNICAL", column_plan.note
    if column_plan.strategy == "derivado_pelo_codigo":
        return "SOURCE_ONLY_TECHNICAL", column_plan.note
    if column_plan.strategy == "nao_migrar":
        reason = column_plan.note or "Metadado nativo Monday; rastreio via ledger/coluna Monday ID"
        return "INTENTIONALLY_NOT_MIGRATED", reason
    if not column_plan.exists_in_target or not column_plan.sunday_column_id:
        return "UNMAPPED", column_plan.note or "Coluna ausente no Sunday destino"
    if column_plan.strategy == "direto":
        return "MAPPED_DIRECT", None
    if column_plan.strategy in {"transformacao", "configurar_manualmente"}:
        return "MAPPED_TRANSFORM", column_plan.note
    return "UNMAPPED", column_plan.note


def build_mapping_matrix(board_plan: BoardPlan) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for column_plan in board_plan.column_plans:
        status, reason = classify_mapping_status(column_plan)
        rows.append(
            {
                "monday_column_id": column_plan.monday_column_id,
                "monday_column_name": column_plan.monday_title,
                "monday_type": column_plan.monday_type,
                "sunday_column_id": column_plan.sunday_column_id,
                "sunday_column_name": column_plan.sunday_target,
                "transformacao": column_plan.strategy,
                "status": status,
                "reason": reason,
            },
        )
    return rows


def _status_key_for_label(
    board_plan: BoardPlan,
    monday_column_id: str,
    label: str | None,
) -> str | None:
    if not label:
        return None
    status_map = board_plan.status_mappings.get(monday_column_id, {})
    key = status_map.get(label)
    if key is None and label not in status_map:
        key = slugify_status_key(label)
    return key


def derive_expected_sunday_value(
    *,
    monday_column: MondayColumnInfo,
    source_text: str | None,
    board_plan: BoardPlan,
) -> object | None:
    text = (source_text or "").strip()
    if not text:
        return None
    if monday_column.type == "status":
        return _status_key_for_label(board_plan, monday_column.id, text)
    explicit = get_explicit_column_mapping(board_plan.monday_board_id, monday_column.id)
    if explicit is not None and explicit.transform == "file_to_link":
        return derive_file_to_link_value(
            source_text=text,
            display_text=explicit.link_display_text or monday_column.title,
        )
    if monday_column.type == "numbers":
        try:
            return float(text.replace(",", "."))
        except ValueError:
            return None
    if monday_column.type == "date":
        return text[:10] if len(text) >= 10 else text
    if monday_column.type in {"text", "long_text", "link", "email", "location", "phone"}:
        return text
    if monday_column.type == "checkbox":
        return text.lower() in {"true", "1", "sim", "yes", "v"}
    if monday_column.type == "dropdown":
        return text
    if monday_column.type == "tags":
        return text
    if monday_column.type == "rating":
        try:
            return float(text.replace(",", "."))
        except ValueError:
            return None
    return None


def _column_plan_by_id(board_plan: BoardPlan) -> dict[str, ColumnPlan]:
    return {plan.monday_column_id: plan for plan in board_plan.column_plans}


def _sunday_column_is_system(snapshot: SundayBoardSnapshot, column_id: str) -> bool:
    for column in snapshot.columns:
        if column.id == column_id:
            return column.is_system
    return False


@dataclass
class FieldAuditRow:
    monday_item_id: str
    sunday_item_id: str
    monday_column_id: str
    field_name: str
    mapping_status: MappingStatus
    result: FieldResult
    source_value: str | None = None
    expected_value: object | None = None
    actual_value: object | None = None
    note: str | None = None


@dataclass
class ItemAuditResult:
    monday_item_id: str
    sunday_item_id: str
    fields: list[FieldAuditRow] = field(default_factory=list)

    @property
    def is_fully_correct(self) -> bool:
        return all(
            row.result in {"MATCH", "OK_EMPTY", "INTENTIONALLY_NOT_MIGRATED"}
            for row in self.fields
        )

    @property
    def is_fully_verified(self) -> bool:
        """True apenas sem divergência nem resolução semântica pendente."""
        blocking = {
            "MISMATCH",
            "MISSING_TARGET_VALUE",
            "UNMAPPED_SOURCE_FIELD",
            "TRANSFORMATION_ERROR",
            "SEMANTIC_RESOLUTION_UNVERIFIED",
        }
        return all(row.result not in blocking for row in self.fields)

    @property
    def has_divergence(self) -> bool:
        return not self.is_fully_correct


@dataclass
class BoardAuditMetrics:
    monday_board_id: str
    sunday_board_id: str
    items_audited: int = 0
    items_fully_correct: int = 0
    items_fully_verified: int = 0
    items_with_divergence: int = 0
    semantic_resolution_unverified: int = 0
    source_non_empty_business_fields: int = 0
    expected_mapped_fields: int = 0
    matched: int = 0
    mismatched: int = 0
    missing_target_values: int = 0
    unmapped_source_fields: int = 0
    intentional_not_migrated: int = 0
    transformation_errors: int = 0
    mapping_matrix: list[dict[str, object]] = field(default_factory=list)
    item_results: list[ItemAuditResult] = field(default_factory=list)

    @property
    def field_fidelity_rate(self) -> float:
        if self.expected_mapped_fields == 0:
            return 1.0
        return self.matched / self.expected_mapped_fields


@dataclass
class CommentAuditMetrics:
    source_updates_migraveis: int = 0
    markers_expected: int = 0
    markers_present: int = 0
    missing: int = 0
    duplicates: int = 0
    metadata_errors: int = 0


def audit_item_fields(
    *,
    inventory: MondayBoardInventory,
    board_plan: BoardPlan,
    sunday_snapshot: SundayBoardSnapshot,
    source: MondayApplySource,
    sunday_item_id: str,
    client,
    monday_id_column_id: str,
    target_group_id: str,
) -> ItemAuditResult:
    column_plans = _column_plan_by_id(board_plan)
    result = ItemAuditResult(
        monday_item_id=source.item_id,
        sunday_item_id=sunday_item_id,
    )
    sunday_item = client.get_item(board_plan.sunday_board_id or "", sunday_item_id)
    if sunday_item is None:
        result.fields.append(
            FieldAuditRow(
                monday_item_id=source.item_id,
                sunday_item_id=sunday_item_id,
                monday_column_id="",
                field_name="__sunday_item__",
                mapping_status="UNMAPPED",
                result="MISSING_TARGET_VALUE",
                note="Item Sunday não encontrado",
            ),
        )
        return result

    system_checks = [
        ("name", source.name, sunday_item.name),
        (
            "monday_id",
            format_monday_id_column_value(inventory.board_id, source.item_id),
            client.get_value(sunday_item_id, monday_id_column_id),
        ),
        (
            "system_status",
            derive_system_status_key(inventory, source.item_id),
            sunday_item.status,
        ),
        ("group_id", target_group_id, sunday_item.group_id),
    ]
    for field_name, expected, actual in system_checks:
        source_text = str(expected) if expected is not None else None
        if _normalize_empty(expected) and _normalize_empty(actual):
            row_result: FieldResult = "OK_EMPTY"
        elif expected == actual:
            row_result = "MATCH"
        else:
            row_result = "MISMATCH"
        result.fields.append(
            FieldAuditRow(
                monday_item_id=source.item_id,
                sunday_item_id=sunday_item_id,
                monday_column_id="system",
                field_name=field_name,
                mapping_status="MAPPED_DIRECT",
                result=row_result,
                source_value=source_text,
                expected_value=expected,
                actual_value=actual,
            ),
        )

    for monday_column in inventory.columns:
        if monday_column.type == "name":
            continue
        plan_column = column_plans.get(monday_column.id)
        if plan_column is None:
            continue
        mapping_status, mapping_reason = classify_mapping_status(plan_column)
        source_text = source.values_by_column_id.get(monday_column.id)
        source_nonempty = not _normalize_empty(source_text)

        if not source_nonempty:
            sunday_col_id = plan_column.sunday_column_id
            skip_statuses = {"SOURCE_ONLY_TECHNICAL", "INTENTIONALLY_NOT_MIGRATED"}
            actual = (
                client.get_value(sunday_item_id, sunday_col_id)
                if sunday_col_id
                and mapping_status not in skip_statuses
                and not _sunday_column_is_system(sunday_snapshot, sunday_col_id)
                else None
            )
            if _normalize_empty(actual):
                continue
            row = FieldAuditRow(
                monday_item_id=source.item_id,
                sunday_item_id=sunday_item_id,
                monday_column_id=monday_column.id,
                field_name=monday_column.title,
                mapping_status=mapping_status,
                result="MISMATCH",
                source_value=None,
                expected_value=None,
                actual_value=actual,
                note="Sunday preenchido sem source",
            )
            result.fields.append(row)
            continue

        if mapping_status == "SOURCE_ONLY_TECHNICAL":
            continue

        if mapping_status == "INTENTIONALLY_NOT_MIGRATED":
            result.fields.append(
                FieldAuditRow(
                    monday_item_id=source.item_id,
                    sunday_item_id=sunday_item_id,
                    monday_column_id=monday_column.id,
                    field_name=monday_column.title,
                    mapping_status=mapping_status,
                    result="INTENTIONALLY_NOT_MIGRATED",
                    source_value=source_text,
                    note=mapping_reason,
                ),
            )
            continue

        if mapping_status == "UNMAPPED":
            result.fields.append(
                FieldAuditRow(
                    monday_item_id=source.item_id,
                    sunday_item_id=sunday_item_id,
                    monday_column_id=monday_column.id,
                    field_name=monday_column.title,
                    mapping_status=mapping_status,
                    result="UNMAPPED_SOURCE_FIELD",
                    source_value=source_text,
                    note=mapping_reason,
                ),
            )
            continue

        if monday_column.type == "formula":
            result.fields.append(
                FieldAuditRow(
                    monday_item_id=source.item_id,
                    sunday_item_id=sunday_item_id,
                    monday_column_id=monday_column.id,
                    field_name=monday_column.title,
                    mapping_status="INTENTIONALLY_NOT_MIGRATED",
                    result="INTENTIONALLY_NOT_MIGRATED",
                    source_value=source_text,
                    note="Fórmula Sunday (Saved) — validar inputs, não valor direto",
                ),
            )
            continue

        if is_file_to_link_mapping(inventory.board_id, monday_column.id):
            explicit = get_explicit_column_mapping(inventory.board_id, monday_column.id)
            sunday_column_id = plan_column.sunday_column_id
            expected = derive_expected_sunday_value(
                monday_column=monday_column,
                source_text=source_text,
                board_plan=board_plan,
            )
            actual = (
                client.get_value(sunday_item_id, sunday_column_id)
                if sunday_column_id
                else None
            )
            if expected is None:
                row_result = "TRANSFORMATION_ERROR"
            elif link_values_equal(expected, actual):
                row_result = "MATCH"
            elif _normalize_empty(actual):
                row_result = "MISSING_TARGET_VALUE"
            else:
                row_result = "MISMATCH"
            result.fields.append(
                FieldAuditRow(
                    monday_item_id=source.item_id,
                    sunday_item_id=sunday_item_id,
                    monday_column_id=monday_column.id,
                    field_name=monday_column.title,
                    mapping_status=mapping_status,
                    result=row_result,
                    source_value=source_text,
                    expected_value=expected,
                    actual_value=actual,
                    note=explicit.documentation_label if explicit else "FILE_TO_LINK",
                ),
            )
            continue

        if monday_column.type in APPLY_WRITER_SKIP_TYPES:
            result.fields.append(
                FieldAuditRow(
                    monday_item_id=source.item_id,
                    sunday_item_id=sunday_item_id,
                    monday_column_id=monday_column.id,
                    field_name=monday_column.title,
                    mapping_status=mapping_status,
                    result="MISSING_TARGET_VALUE",
                    source_value=source_text,
                    note="Tipo omitido pelo apply_writer atual",
                ),
            )
            continue

        sunday_column_id = plan_column.sunday_column_id
        if not sunday_column_id:
            result.fields.append(
                FieldAuditRow(
                    monday_item_id=source.item_id,
                    sunday_item_id=sunday_item_id,
                    monday_column_id=monday_column.id,
                    field_name=monday_column.title,
                    mapping_status=mapping_status,
                    result="MISSING_TARGET_VALUE",
                    source_value=source_text,
                    note="Mapping sem sunday_column_id",
                ),
            )
            continue

        expected = derive_expected_sunday_value(
            monday_column=monday_column,
            source_text=source_text,
            board_plan=board_plan,
        )
        actual = client.get_value(sunday_item_id, sunday_column_id)

        if expected is None:
            row_result = "TRANSFORMATION_ERROR"
        elif monday_column.type == "status" and isinstance(expected, str):
            sunday_column = next(
                (column for column in sunday_snapshot.columns if column.id == sunday_column_id),
                None,
            )
            status_options: list[dict] = []
            if sunday_column is not None:
                status_options = list((sunday_column.settings or {}).get("options", []))
            row_result = _audit_status_field_result(
                expected=expected,
                actual=actual,
                source_text=source_text,
                status_options=status_options,
            )
        elif _values_equal(expected, actual):
            row_result = "MATCH"
        elif _normalize_empty(actual):
            row_result = "MISSING_TARGET_VALUE"
        else:
            row_result = "MISMATCH"

        result.fields.append(
            FieldAuditRow(
                monday_item_id=source.item_id,
                sunday_item_id=sunday_item_id,
                monday_column_id=monday_column.id,
                field_name=monday_column.title,
                mapping_status=mapping_status,
                result=row_result,
                source_value=source_text,
                expected_value=expected,
                actual_value=actual,
            ),
        )

    return result


def _audit_status_field_result(
    *,
    expected: str,
    actual: object,
    source_text: str | None,
    status_options: list[dict],
) -> FieldResult:
    if _normalize_empty(actual):
        return "MISSING_TARGET_VALUE"

    actual_str = str(actual)
    try:
        resolved = resolve_sunday_custom_status_option(
            column_options=status_options,
            semantic_key=expected,
            monday_label=source_text,
        )
        if actual_str == resolved.option_key:
            return "MATCH"
        if actual_str == expected:
            return "MATCH"
    except StatusResolveError:
        if actual_str == expected:
            return "SEMANTIC_RESOLUTION_UNVERIFIED"

    return "MISMATCH"


def _values_equal(expected: object, actual: object) -> bool:
    if link_values_equal(expected, actual):
        return True
    if isinstance(expected, float) and isinstance(actual, (int, float, str)):
        try:
            return abs(expected - float(str(actual).replace(",", "."))) < 1e-6
        except ValueError:
            return False
    return expected == actual



def aggregate_board_metrics(
    *,
    monday_board_id: str,
    sunday_board_id: str,
    mapping_matrix: list[dict[str, object]],
    item_results: list[ItemAuditResult],
) -> BoardAuditMetrics:
    metrics = BoardAuditMetrics(
        monday_board_id=monday_board_id,
        sunday_board_id=sunday_board_id,
        mapping_matrix=mapping_matrix,
        item_results=item_results,
        items_audited=len(item_results),
    )
    for item in item_results:
        if item.is_fully_correct:
            metrics.items_fully_correct += 1
        else:
            metrics.items_with_divergence += 1
        if item.is_fully_verified:
            metrics.items_fully_verified += 1
        for row in item.fields:
            if row.field_name in {"name", "monday_id", "system_status", "group_id"}:
                metrics.source_non_empty_business_fields += 1
                metrics.expected_mapped_fields += 1
                if row.result == "MATCH":
                    metrics.matched += 1
                elif row.result == "MISMATCH":
                    metrics.mismatched += 1
                elif row.result == "MISSING_TARGET_VALUE":
                    metrics.missing_target_values += 1
                continue

            if row.result == "INTENTIONALLY_NOT_MIGRATED":
                metrics.intentional_not_migrated += 1
                continue
            if row.result == "OK_EMPTY":
                continue

            metrics.source_non_empty_business_fields += 1

            if row.result == "UNMAPPED_SOURCE_FIELD":
                metrics.unmapped_source_fields += 1
                continue

            if row.mapping_status in {"MAPPED_DIRECT", "MAPPED_TRANSFORM"}:
                metrics.expected_mapped_fields += 1

            if row.result == "MATCH":
                metrics.matched += 1
            elif row.result == "MISMATCH":
                metrics.mismatched += 1
            elif row.result == "MISSING_TARGET_VALUE":
                metrics.missing_target_values += 1
            elif row.result == "TRANSFORMATION_ERROR":
                metrics.transformation_errors += 1
            elif row.result == "SEMANTIC_RESOLUTION_UNVERIFIED":
                metrics.semantic_resolution_unverified += 1
            elif row.result == "UNMAPPED_SOURCE_FIELD":
                metrics.unmapped_source_fields += 1

    return metrics


def audit_board_migrated_items(
    *,
    monday_board_id: str,
    inventory: MondayBoardInventory,
    sunday_snapshot: SundayBoardSnapshot,
    apply_sources: dict[str, MondayApplySource],
    client,
    monday_id_column_id: str,
    target_group_id: str,
    ledger_records: dict[str, dict] | None = None,
) -> BoardAuditMetrics:
    ledger = ledger_records if ledger_records is not None else load_persistent_ledger()
    board_plan = build_board_plan(
        inventory,
        sunday_snapshot,
        sunday_board_by_monday_map(),
    )
    mapping_matrix = build_mapping_matrix(board_plan)
    item_results: list[ItemAuditResult] = []
    for key, record in ledger.items():
        if record.get("monday_board_id") != monday_board_id:
            continue
        if record.get("migration_status") != "migrated":
            continue
        monday_item_id = str(record.get("monday_item_id", ""))
        sunday_item_id = str(record.get("sunday_item_id", ""))
        source = apply_sources.get(monday_item_id)
        if source is None:
            item_results.append(
                ItemAuditResult(
                    monday_item_id=monday_item_id,
                    sunday_item_id=sunday_item_id,
                    fields=[
                        FieldAuditRow(
                            monday_item_id=monday_item_id,
                            sunday_item_id=sunday_item_id,
                            monday_column_id="",
                            field_name="__monday_source__",
                            mapping_status="UNMAPPED",
                            result="MISSING_TARGET_VALUE",
                            note="Source Monday não encontrada",
                        ),
                    ],
                ),
            )
            continue
        item_results.append(
            audit_item_fields(
                inventory=inventory,
                board_plan=board_plan,
                sunday_snapshot=sunday_snapshot,
                source=source,
                sunday_item_id=sunday_item_id,
                client=client,
                monday_id_column_id=monday_id_column_id,
                target_group_id=target_group_id,
            ),
        )
    return aggregate_board_metrics(
        monday_board_id=monday_board_id,
        sunday_board_id=sunday_snapshot.board_id,
        mapping_matrix=mapping_matrix,
        item_results=item_results,
    )


def classify_missing_comment_marker(
    *,
    update_created_at: str | None,
    migrated_at: str | None,
    source_snapshot_timestamp: str | None,
) -> Literal["MIGRATION_MISS", "POST_MIGRATION_DELTA", "INCONCLUSIVE"]:
    """Classifica marker ausente sem expor conteúdo do comment."""
    from datetime import datetime

    def _parse(value: str | None):
        if not value:
            return None
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    created = _parse(update_created_at)
    migrated = _parse(migrated_at)
    snapshot = _parse(source_snapshot_timestamp)
    if created and migrated and created > migrated:
        return "POST_MIGRATION_DELTA"
    if created and snapshot and created <= snapshot:
        return "MIGRATION_MISS"
    if created and migrated and created <= migrated:
        return "MIGRATION_MISS"
    return "INCONCLUSIVE"


def audit_comments_for_items(
    *,
    inventory: MondayBoardInventory,
    monday_item_ids: set[str],
    sunday_client,
    monday_id_index: dict[str, str],
) -> CommentAuditMetrics:
    metrics = CommentAuditMetrics()
    diagnostics_by_item = {item.item_id: item.update_diagnostics for item in inventory.items}
    seen_markers: set[str] = set()

    for monday_item_id in sorted(monday_item_ids):
        migratable = tuple(
            update
            for update in diagnostics_by_item.get(monday_item_id, ())
            if update.is_migratable
        )
        metrics.source_updates_migraveis += len(migratable)
        sunday_item_id = monday_id_index.get(monday_item_id)
        if not sunday_item_id:
            metrics.missing += len(migratable)
            continue

        expected_markers = {
            comment_idempotency_marker(monday_item_id, update.update_id)
            for update in migratable
        }
        metrics.markers_expected += len(expected_markers)

        present: set[str] = set()
        for comment in sunday_client.list_comments(sunday_item_id):
            lines = {line.strip() for line in comment.body.splitlines() if line.strip()}
            for marker in expected_markers:
                if marker in lines:
                    if marker in seen_markers:
                        metrics.duplicates += 1
                    seen_markers.add(marker)
                    present.add(marker)
            for update in migratable:
                marker = comment_idempotency_marker(monday_item_id, update.update_id)
                if marker not in lines:
                    continue
                if update.has_author and "autor original:" not in comment.body.lower():
                    metrics.metadata_errors += 1
                if update.created_at and "data original:" not in comment.body.lower():
                    metrics.metadata_errors += 1

        metrics.markers_present += len(present)
        metrics.missing += len(expected_markers - present)

    return metrics


def summarize_mapping_coverage(
    matrices: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for board_id, matrix in matrices.items():
        business_cols = [
            row
            for row in matrix
            if row["status"] != "SOURCE_ONLY_TECHNICAL"
        ]
        rows.append(
            {
                "board": board_id,
                "source_business_cols": len(business_cols),
                "mapped_direct": sum(1 for r in business_cols if r["status"] == "MAPPED_DIRECT"),
                "mapped_transform": sum(
                    1 for r in business_cols if r["status"] == "MAPPED_TRANSFORM"
                ),
                "intentional": sum(
                    1 for r in business_cols if r["status"] == "INTENTIONALLY_NOT_MIGRATED"
                ),
                "unmapped": sum(1 for r in business_cols if r["status"] == "UNMAPPED"),
            },
        )
    return rows


def explain_legacy_field_checker() -> dict[str, object]:
    return {
        "compares_only_planned_subset": True,
        "skips_apply_writer_types": sorted(APPLY_WRITER_SKIP_TYPES),
        "skips_when_expected_none": True,
        "skips_unmapped_target_columns": True,
        "skips_source_fields_without_target_column": True,
        "could_produce_false_100_percent": True,
        "semantic_resolution_unverified_not_counted_as_verified": True,
        "location": "apply_writer.verify_applied_board",
    }
