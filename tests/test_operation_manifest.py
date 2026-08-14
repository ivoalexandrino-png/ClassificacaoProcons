"""Testes do manifesto canônico v2 e safety model escopado."""

from __future__ import annotations

from pathlib import Path

from classificacao_procons.migration.apply_writer import MondayApplySource
from classificacao_procons.migration.column_transforms import (
    PROCONS_DOCS_SAC_MONDAY_COLUMN,
    PROCONS_NOTIFICACAO_MONDAY_COLUMN,
)
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
    MIGRATION_RUNTIME_MODULE_PATHS,
    attach_scoped_safety_metadata,
    board_global_fingerprint,
    build_scoped_operation_manifest,
    compare_scoped_drift,
    migration_code_revision,
    migration_code_revision_for_module_bytes,
    migration_schema_fingerprint,
    operation_manifest_hash_v1,
    operation_manifest_hash_v2,
    plan_item_manifest_operations,
    selected_source_fingerprint,
    summarize_custom_write_breakdown,
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
            MondayColumnInfo(
                id=PROCONS_NOTIFICACAO_MONDAY_COLUMN,
                title="Arquivos",
                type="file",
            ),
            MondayColumnInfo(
                id=PROCONS_DOCS_SAC_MONDAY_COLUMN,
                title="Arquivos8",
                type="file",
            ),
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
            ColumnPlan(
                monday_column_id=PROCONS_NOTIFICACAO_MONDAY_COLUMN,
                monday_title="Arquivos",
                monday_type="file",
                strategy="transformacao",
                sunday_target="notificacao_procon",
                sunday_column_id="598",
                exists_in_target=True,
            ),
            ColumnPlan(
                monday_column_id=PROCONS_DOCS_SAC_MONDAY_COLUMN,
                monday_title="Arquivos8",
                monday_type="file",
                strategy="transformacao",
                sunday_target="docs_sac",
                sunday_column_id="605",
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
                id="598",
                key="notificacao_procon",
                label="Notificação Procon",
                type="link",
                is_system=False,
            ),
            SundayColumnSnapshot(
                id="605",
                key="docs_sac",
                label="Docs SAC",
                type="link",
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


def _source(
    item_id: str,
    *,
    status: str = "Aberto",
    text: str = "nota",
    notificacao_url: str | None = None,
    docs_url: str | None = None,
) -> MondayApplySource:
    values = {
        "status_main": status,
        "text_col": text,
    }
    if notificacao_url:
        values[PROCONS_NOTIFICACAO_MONDAY_COLUMN] = notificacao_url
    if docs_url:
        values[PROCONS_DOCS_SAC_MONDAY_COLUMN] = docs_url
    return MondayApplySource(
        item_id=item_id,
        name=f"Item {item_id}",
        group_id="g1",
        values_by_column_id=values,
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
            snapshot_a.columns[3],
            snapshot_a.columns[4],
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


def test_manifest_hash_v2_changes_when_operation_count_changes():
    inventory = _inventory(_item(ITEM_A))
    board_plan = _board_plan()
    sunday_snapshot = _sunday_snapshot()
    manifest_one = build_scoped_operation_manifest(
        plan_operations=[_create_operation(ITEM_A)],
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
    manifest_two = build_scoped_operation_manifest(
        plan_operations=[_create_operation(ITEM_A, updates=(update,))],
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources={ITEM_A: _source(ITEM_A)},
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    assert operation_manifest_hash_v2(manifest_one) != operation_manifest_hash_v2(manifest_two)


def test_manifest_hash_v2_changes_when_payload_changes_but_op_id_same():
    inventory = _inventory(_item(ITEM_A))
    board_plan = _board_plan()
    sunday_snapshot = _sunday_snapshot()
    manifest_before = build_scoped_operation_manifest(
        plan_operations=[_create_operation(ITEM_A)],
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources={ITEM_A: _source(ITEM_A, text="nota-a")},
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    manifest_after = build_scoped_operation_manifest(
        plan_operations=[_create_operation(ITEM_A)],
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources={ITEM_A: _source(ITEM_A, text="nota-b")},
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    text_ops_before = [
        op
        for op in manifest_before
        if op.kind == "CUSTOM_FIELD_WRITE" and op.monday_column_id == "text_col"
    ]
    text_ops_after = [
        op
        for op in manifest_after
        if op.kind == "CUSTOM_FIELD_WRITE" and op.monday_column_id == "text_col"
    ]
    assert text_ops_before and text_ops_after
    assert text_ops_before[0].op_id == text_ops_after[0].op_id
    assert text_ops_before[0].payload_digest != text_ops_after[0].payload_digest
    assert operation_manifest_hash_v1(manifest_before) == operation_manifest_hash_v1(manifest_after)
    assert operation_manifest_hash_v2(manifest_before) != operation_manifest_hash_v2(manifest_after)


def test_url_change_changes_manifest_hash_v2():
    inventory = _inventory(_item(ITEM_A))
    board_plan = _board_plan()
    sunday_snapshot = _sunday_snapshot()
    manifest_a = build_scoped_operation_manifest(
        plan_operations=[_create_operation(ITEM_A)],
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources={
            ITEM_A: _source(
                ITEM_A,
                notificacao_url="https://files.example/a.pdf",
            ),
        },
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    manifest_b = build_scoped_operation_manifest(
        plan_operations=[_create_operation(ITEM_A)],
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources={
            ITEM_A: _source(
                ITEM_A,
                notificacao_url="https://files.example/b.pdf",
            ),
        },
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    assert operation_manifest_hash_v2(manifest_a) != operation_manifest_hash_v2(manifest_b)


def test_link_and_status_not_double_counted_in_operation_total():
    inventory = _inventory(_item(ITEM_A))
    manifest = build_scoped_operation_manifest(
        plan_operations=[_create_operation(ITEM_A)],
        inventory=inventory,
        board_plan=_board_plan(),
        sunday_snapshot=_sunday_snapshot(),
        apply_sources={
            ITEM_A: _source(
                ITEM_A,
                notificacao_url="https://files.example/a.pdf",
                docs_url="https://files.example/b.pdf",
            ),
        },
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    accounting = summarize_manifest_accounting(manifest)
    breakdown = summarize_custom_write_breakdown(manifest, inventory=inventory)
    assert accounting.link_writes == breakdown.link
    assert accounting.status_writes == breakdown.status
    assert accounting.all_custom_column_writes == (
        accounting.custom_other_writes + accounting.status_writes + accounting.link_writes
    )
    assert accounting.operation_total == (
        accounting.sunday_write_operations + accounting.ledger_operations
    )
    assert accounting.sunday_write_operations == sum(
        (
            accounting.item_creates,
            accounting.system_writes,
            accounting.custom_other_writes,
            accounting.status_writes,
            accounting.link_writes,
            accounting.comments,
            accounting.attachments,
            accounting.relations,
            accounting.subitems,
        ),
    )


def test_link_write_has_no_duplicate_custom_field_write():
    manifest = build_scoped_operation_manifest(
        plan_operations=[_create_operation(ITEM_A)],
        inventory=_inventory(_item(ITEM_A)),
        board_plan=_board_plan(),
        sunday_snapshot=_sunday_snapshot(),
        apply_sources={
            ITEM_A: _source(
                ITEM_A,
                notificacao_url="https://files.example/a.pdf",
            ),
        },
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    link_ops = [op for op in manifest if op.kind == "LINK_WRITE"]
    assert len(link_ops) == 1
    link = link_ops[0]
    duplicate_custom = [
        op
        for op in manifest
        if op.kind == "CUSTOM_FIELD_WRITE"
        and op.monday_column_id == link.monday_column_id
    ]
    assert duplicate_custom == []


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
    assert accounting.system_writes == len(system_ops) == 2
    assert ("name", "status_sistema") == tuple(
        sorted(op.field_name for op in system_ops),
    )
    monday_id_ops = [op for op in manifest if op.field_name == "monday_id"]
    assert len(monday_id_ops) == 1
    assert monday_id_ops[0].kind == "CUSTOM_FIELD_WRITE"


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


def test_validate_scoped_apply_aborts_on_manifest_v2_change():
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
    assert "operation_manifest_hash_v2 divergente" in failures


def test_code_revision_change_invalidates_approval():
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
    current = attach_scoped_safety_metadata(
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=sunday_snapshot,
        apply_sources=sources,
        plan_operations=[_create_operation(ITEM_A)],
        selected_item_ids=selected,
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    object.__setattr__(current, "code_revision", "deadbeefdeadbeefdeadbeef")
    failures = validate_scoped_apply_fingerprints(approved=approved, current=current)
    assert "code_revision divergente" in failures


def test_migration_code_revision_is_stable_for_same_sources():
    revision_a = migration_code_revision(repo_root=Path(__file__).resolve().parents[1])
    revision_b = migration_code_revision(repo_root=Path(__file__).resolve().parents[1])
    assert revision_a == revision_b


def test_migration_runtime_module_paths_cover_execution_engine():
    paths = set(MIGRATION_RUNTIME_MODULE_PATHS)
    assert "scripts/sunday_migration_execute.py" in paths
    assert "src/classificacao_procons/migration/apply_writer.py" in paths
    assert "src/classificacao_procons/migration/executor.py" in paths
    assert "src/classificacao_procons/migration/operation_manifest.py" in paths
    assert "src/classificacao_procons/migration/source_completeness.py" in paths
    assert "src/classificacao_procons/migration/status_coverage.py" in paths


def test_code_revision_changes_when_cli_execution_path_changes():
    repo_root = Path(__file__).resolve().parents[1]
    cli_path = "scripts/sunday_migration_execute.py"
    current = (repo_root / cli_path).read_bytes()
    before_hotfix = current + b"\n"
    revision_before = migration_code_revision_for_module_bytes(
        repo_root=repo_root,
        module_bytes={cli_path: before_hotfix},
    )
    revision_after = migration_code_revision(repo_root=repo_root)
    assert revision_before != revision_after


def test_code_revision_rejects_stale_approval_after_runtime_change():
    repo_root = Path(__file__).resolve().parents[1]
    approved = attach_scoped_safety_metadata(
        inventory=_inventory(_item(ITEM_A)),
        board_plan=_board_plan(),
        sunday_snapshot=_sunday_snapshot(),
        apply_sources={ITEM_A: _source(ITEM_A)},
        plan_operations=[_create_operation(ITEM_A)],
        selected_item_ids=frozenset({ITEM_A}),
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    stale_revision = migration_code_revision_for_module_bytes(
        repo_root=repo_root,
        module_bytes={
            "src/classificacao_procons/migration/apply_writer.py": b"stale-engine",
        },
    )
    current = attach_scoped_safety_metadata(
        inventory=_inventory(_item(ITEM_A)),
        board_plan=_board_plan(),
        sunday_snapshot=_sunday_snapshot(),
        apply_sources={ITEM_A: _source(ITEM_A)},
        plan_operations=[_create_operation(ITEM_A)],
        selected_item_ids=frozenset({ITEM_A}),
        monday_id_column_id="999",
        monday_board_id=PROCONS,
    )
    object.__setattr__(current, "code_revision", stale_revision)
    failures = validate_scoped_apply_fingerprints(approved=approved, current=current)
    assert "code_revision divergente" in failures
