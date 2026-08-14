"""Testes do manifesto canônico e safety model escopado."""

from __future__ import annotations

from classificacao_procons.migration.apply_writer import MondayApplySource
from classificacao_procons.migration.executor import PlannedOperation
from classificacao_procons.migration.models import (
    BoardPlan,
    ColumnPlan,
    MondayBoardInventory,
    MondayColumnInfo,
    MondayItemDigest,
    MondayUpdateDigest,
    SundayBoardSnapshot,
    SundayColumnSnapshot,
)
from classificacao_procons.migration.operation_manifest import (
    attach_scoped_safety_metadata,
    board_global_fingerprint,
    build_scoped_operation_manifest,
    compare_scoped_drift,
    migration_schema_fingerprint,
    operation_manifest_hash,
    plan_item_manifest_operations,
    selected_source_fingerprint,
    summarize_manifest_accounting,
    validate_scoped_apply_fingerprints,
)

PROCONS = "4944254220"
ITEM_A = "10021122897"
ITEM_B = "10051458135"


def _inventory(*items: MondayItemDigest) -> MondayBoardInventory:
    return MondayBoardInventory(
        board_id=PROCONS,
        name="Procons",
        groups={"g1": "2025", "g2": "Itens"},
        columns=(
            MondayColumnInfo(id="name", title="Name", type="name"),
            MondayColumnInfo(id="status_main", title="Status", type="status"),
            MondayColumnInfo(id="text_col", title="Obs", type="text"),
            MondayColumnInfo(id="monday_id_col", title="Monday ID", type="text"),
        ),
        items=items,
    )


def _item(
    item_id: str,
    *,
    updated_at: str = "2026-01-01T00:00:00Z",
    status_labels: dict[str, str] | None = None,
    updates: tuple[MondayUpdateDigest, ...] = (),
) -> MondayItemDigest:
    return MondayItemDigest(
        item_id=item_id,
        group_id="g1",
        created_at="2025-01-01T00:00:00Z",
        updated_at=updated_at,
        status_labels=status_labels or {"status_main": "Aberto"},
        update_diagnostics=updates,
        updates_count_is_exact=True,
    )


def _board_plan() -> BoardPlan:
    return BoardPlan(
        monday_board_id=PROCONS,
        monday_name="Procons",
        domain="procons",
        sunday_board_id="82",
        sunday_name="Procons Sunday",
        confidence="alta",
        column_plans=(
            ColumnPlan(
                monday_column_id="status_main",
                monday_title="Status",
                monday_type="status",
                strategy="transformacao",
                sunday_target="status_main",
                sunday_column_id="611",
                exists_in_target=True,
            ),
            ColumnPlan(
                monday_column_id="text_col",
                monday_title="Obs",
                monday_type="text",
                strategy="direto",
                sunday_target="text_col",
                sunday_column_id="700",
                exists_in_target=True,
            ),
        ),
        status_mappings={
            "status_main": {"Aberto": "aberto"},
        },
    )


def _sunday_snapshot() -> SundayBoardSnapshot:
    return SundayBoardSnapshot(
        board_id="82",
        name="Procons",
        columns=(
            SundayColumnSnapshot(
                id="611",
                key="status_main",
                label="Status",
                type="status",
                is_system=False,
                settings={"options": [{"key": "opt_1", "label": "Aberto"}]},
            ),
            SundayColumnSnapshot(
                id="700",
                key="text_col",
                label="Obs",
                type="text",
                is_system=False,
            ),
            SundayColumnSnapshot(
                id="999",
                key="monday_id",
                label="Monday ID",
                type="text",
                is_system=False,
            ),
        ),
        groups={"grp1": "Itens"},
    )


def _source(item_id: str, *, status: str = "Aberto", text: str = "nota") -> MondayApplySource:
    return MondayApplySource(
        item_id=item_id,
        name=f"Item {item_id}",
        group_id="g1",
        values_by_column_id={
            "status_main": status,
            "text_col": text,
        },
    )


def _create_operation(
    item_id: str,
    updates: tuple[MondayUpdateDigest, ...] = (),
) -> PlannedOperation:
    return PlannedOperation(
        monday_item_id=item_id,
        disposition="CREATE",
        wave="WAVE_1",
        action="create",
        target_group="2025",
        group_action="preservar",
        system_fields=("name", "monday_id", "status_sistema(derivado)"),
        custom_values_count=1,
        comments_to_create=len(updates),
        update_diagnostics=updates,
        comments_count_exact=True,
    )


def test_global_fingerprint_changes_when_out_of_scope_item_changes():
    base = _inventory(_item(ITEM_A), _item(ITEM_B))
    changed = _inventory(_item(ITEM_A), _item(ITEM_B, updated_at="2026-02-01T00:00:00Z"))
    extra = _inventory(_item(ITEM_A), _item(ITEM_B), _item("99999999999"))
    assert board_global_fingerprint(base) != board_global_fingerprint(changed)
    assert board_global_fingerprint(base) != board_global_fingerprint(extra)


def test_selected_fingerprint_ignores_out_of_scope_item_change():
    board_plan = _board_plan()
    base = _inventory(_item(ITEM_A), _item(ITEM_B))
    extra = _inventory(_item(ITEM_A), _item(ITEM_B), _item("99999999999"))
    sources = {ITEM_A: _source(ITEM_A), ITEM_B: _source(ITEM_B)}
    selected = frozenset({ITEM_A, ITEM_B})
    assert selected_source_fingerprint(
        inventory=base,
        board_plan=board_plan,
        apply_sources=sources,
        item_ids=selected,
    ) == selected_source_fingerprint(
        inventory=extra,
        board_plan=board_plan,
        apply_sources=sources,
        item_ids=selected,
    )


def test_selected_fingerprint_changes_when_selected_item_changes():
    board_plan = _board_plan()
    inventory = _inventory(_item(ITEM_A), _item(ITEM_B))
    sources_before = {ITEM_A: _source(ITEM_A), ITEM_B: _source(ITEM_B)}
    sources_after = {ITEM_A: _source(ITEM_A, text="alterado"), ITEM_B: _source(ITEM_B)}
    selected = frozenset({ITEM_A, ITEM_B})
    assert selected_source_fingerprint(
        inventory=inventory,
        board_plan=board_plan,
        apply_sources=sources_before,
        item_ids=selected,
    ) != selected_source_fingerprint(
        inventory=inventory,
        board_plan=board_plan,
        apply_sources=sources_after,
        item_ids=selected,
    )


def test_new_comment_on_selected_item_changes_selected_fingerprint():
    board_plan = _board_plan()
    update = MondayUpdateDigest(
        update_id="u1",
        created_at="2026-01-01T00:00:00Z",
        has_author=False,
        classification="text_update_without_author",
        is_migratable=True,
    )
    before = _inventory(_item(ITEM_A))
    after = _inventory(_item(ITEM_A, updates=(update,)))
    sources = {ITEM_A: _source(ITEM_A)}
    selected = frozenset({ITEM_A})
    assert selected_source_fingerprint(
        inventory=before,
        board_plan=board_plan,
        apply_sources=sources,
        item_ids=selected,
    ) != selected_source_fingerprint(
        inventory=after,
        board_plan=board_plan,
        apply_sources=sources,
        item_ids=selected,
    )


def test_file_on_selected_item_changes_selected_fingerprint():
    board_plan = _board_plan()
    before = _inventory(_item(ITEM_A))
    after = _inventory(
        MondayItemDigest(
            item_id=ITEM_A,
            group_id="g1",
            created_at="2025-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            status_labels={"status_main": "Aberto"},
            file_count=1,
            updates_count_is_exact=True,
        ),
    )
    sources = {ITEM_A: _source(ITEM_A)}
    selected = frozenset({ITEM_A})
    assert selected_source_fingerprint(
        inventory=before,
        board_plan=board_plan,
        apply_sources=sources,
        item_ids=selected,
    ) != selected_source_fingerprint(
        inventory=after,
        board_plan=board_plan,
        apply_sources=sources,
        item_ids=selected,
    )


def test_schema_fingerprint_changes_when_status_option_changes():
    inventory = _inventory(_item(ITEM_A))
    board_plan = _board_plan()
    snapshot_a = _sunday_snapshot()
    snapshot_b = SundayBoardSnapshot(
        board_id="82",
        name="Procons",
        columns=(
            SundayColumnSnapshot(
                id="611",
                key="status_main",
                label="Status",
                type="status",
                is_system=False,
                settings={"options": [{"key": "opt_9", "label": "Novo"}]},
            ),
            snapshot_a.columns[1],
            snapshot_a.columns[2],
        ),
        groups=snapshot_a.groups,
    )
    assert migration_schema_fingerprint(
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=snapshot_a,
    ) != migration_schema_fingerprint(
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=snapshot_b,
    )


def test_manifest_hash_changes_when_operation_count_changes():
    inventory = _inventory(_item(ITEM_A))
    board_plan = _board_plan()
    sunday_snapshot = _sunday_snapshot()
    operation = _create_operation(ITEM_A)
    manifest_one = build_scoped_operation_manifest(
        plan_operations=[operation],
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources={ITEM_A: _source(ITEM_A)},
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    update = MondayUpdateDigest(
        update_id="u1",
        created_at="2026-01-01T00:00:00Z",
        has_author=False,
        classification="text_update_without_author",
        is_migratable=True,
    )
    operation_two = _create_operation(ITEM_A, updates=(update,))
    manifest_two = build_scoped_operation_manifest(
        plan_operations=[operation_two],
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources={ITEM_A: _source(ITEM_A)},
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    assert operation_manifest_hash(manifest_one) != operation_manifest_hash(manifest_two)


def test_status_subset_not_double_counted_in_operation_total():
    inventory = _inventory(_item(ITEM_A))
    board_plan = _board_plan()
    sunday_snapshot = _sunday_snapshot()
    manifest = build_scoped_operation_manifest(
        plan_operations=[_create_operation(ITEM_A)],
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources={ITEM_A: _source(ITEM_A)},
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    accounting = summarize_manifest_accounting(manifest)
    assert accounting.status_within_custom_fields <= accounting.custom_fields_total
    assert accounting.non_status_custom_fields == (
        accounting.custom_fields_total - accounting.status_within_custom_fields
    )
    assert accounting.operation_total == (
        accounting.sunday_write_operations + accounting.ledger_entries
    )


def test_plan_proxy_custom_values_differs_from_manifest_custom_total():
    inventory = _inventory(_item(ITEM_A))
    proxy_count = len(inventory.items[0].status_labels)
    manifest = build_scoped_operation_manifest(
        plan_operations=[_create_operation(ITEM_A)],
        inventory=inventory,
        board_plan=_board_plan(),
        sunday_snapshot=_sunday_snapshot(),
        apply_sources={ITEM_A: _source(ITEM_A)},
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    accounting = summarize_manifest_accounting(manifest)
    assert proxy_count == 1
    assert accounting.custom_fields_total > proxy_count


def test_system_field_accounting_matches_writer_semantics():
    manifest = plan_item_manifest_operations(
        monday_board_id=PROCONS,
        operation=_create_operation(ITEM_A),
        inventory=_inventory(_item(ITEM_A)),
        board_plan=_board_plan(),
        sunday_snapshot=_sunday_snapshot(),
        apply_source=_source(ITEM_A),
        monday_id_column_id="999",
    )
    accounting = summarize_manifest_accounting(manifest)
    system_ops = [op for op in manifest if op.kind == "SYSTEM_FIELD_WRITE"]
    assert accounting.system_fields == len(system_ops) == 2
    assert ("name", "status_sistema") == tuple(
        sorted(op.field_name for op in system_ops),
    )


def test_scoped_drift_allows_global_change_when_selected_unchanged():
    board_plan = _board_plan()
    sunday_snapshot = _sunday_snapshot()
    base = _inventory(_item(ITEM_A), _item(ITEM_B))
    extra = _inventory(_item(ITEM_A), _item(ITEM_B), _item("999"))
    sources = {ITEM_A: _source(ITEM_A), ITEM_B: _source(ITEM_B)}
    selected = frozenset({ITEM_A, ITEM_B})
    operations = [
        _create_operation(ITEM_A),
        _create_operation(ITEM_B),
    ]
    approved = attach_scoped_safety_metadata(
        inventory=base,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources=sources,
        plan_operations=operations,
        selected_item_ids=selected,
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    current = attach_scoped_safety_metadata(
        inventory=extra,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources=sources,
        plan_operations=operations,
        selected_item_ids=selected,
        monday_id_column_id="999",
        monday_board_id=PROCONS,
        approved_board_global_fingerprint=approved.board_global_fingerprint,
    )
    board_changed, selected_changed, schema_changed, scope_safe = compare_scoped_drift(
        approved=approved,
        current=current,
    )
    assert board_changed is True
    assert selected_changed is False
    assert schema_changed is False
    assert scope_safe is True
    assert validate_scoped_apply_fingerprints(approved=approved, current=current) == []


def test_validate_scoped_apply_aborts_on_manifest_change():
    board_plan = _board_plan()
    sunday_snapshot = _sunday_snapshot()
    inventory = _inventory(_item(ITEM_A))
    sources = {ITEM_A: _source(ITEM_A)}
    selected = frozenset({ITEM_A})
    approved = attach_scoped_safety_metadata(
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources=sources,
        plan_operations=[_create_operation(ITEM_A)],
        selected_item_ids=selected,
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    changed_sources = {ITEM_A: _source(ITEM_A, text="novo")}
    current = attach_scoped_safety_metadata(
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources=changed_sources,
        plan_operations=[_create_operation(ITEM_A)],
        selected_item_ids=selected,
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    failures = validate_scoped_apply_fingerprints(approved=approved, current=current)
    assert failures
