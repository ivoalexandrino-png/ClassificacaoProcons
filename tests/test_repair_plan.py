"""Testes de transforms explícitos e repair PLAN Procons."""

from __future__ import annotations

from classificacao_procons.migration.apply_writer import MondayApplySource
from classificacao_procons.migration.column_transforms import (
    PROCONS_CANCELAMENTO_MONDAY_COLUMN,
    PROCONS_CANCELAMENTO_SUNDAY_COLUMN,
    PROCONS_DOCS_SAC_MONDAY_COLUMN,
    PROCONS_NOTIFICACAO_MONDAY_COLUMN,
    derive_file_to_link_value,
    get_explicit_column_mapping,
    link_values_equal,
)
from classificacao_procons.migration.mappings import build_board_plan, sunday_board_by_monday_map
from classificacao_procons.migration.models import (
    MondayBoardInventory,
    MondayColumnInfo,
    SundayBoardSnapshot,
    SundayColumnSnapshot,
)
from classificacao_procons.migration.repair_plan import (
    RepairPlanAbort,
    build_repair_plan,
    evaluate_repair_gate,
    should_block_field_for_source_change,
)
from classificacao_procons.migration.source_audit import derive_expected_sunday_value
from classificacao_procons.migration.source_completeness import (
    check_source_completeness_for_sources,
)


class FakeSundayClient:
    def __init__(self, *, values: dict[str, object], status: str = "to_do"):
        self.values = values
        self.status = status

    def get_item(self, board_id: str, item_id: str):
        class Item:
            name = "Item"
            status = self.status
            group_id = "g_itens"

        return Item()

    def get_value(self, item_id: str, column_id: str):
        return self.values.get(column_id)


def _procons_inventory() -> MondayBoardInventory:
    return MondayBoardInventory(
        board_id="4944254220",
        name="Procons",
        groups={"g1": "Pendentes"},
        columns=(
            MondayColumnInfo(id="name", title="Name", type="name"),
            MondayColumnInfo(
                id=PROCONS_CANCELAMENTO_MONDAY_COLUMN,
                title="Houve Cancelamento de Assinatura?",
                type="status",
                settings={"labels": {"0": "Não", "1": "Sim"}},
            ),
            MondayColumnInfo(
                id=PROCONS_NOTIFICACAO_MONDAY_COLUMN,
                title="Notificação Procon",
                type="file",
            ),
            MondayColumnInfo(id=PROCONS_DOCS_SAC_MONDAY_COLUMN, title="Docs SAC", type="file"),
            MondayColumnInfo(id="status8", title="Status", type="status"),
        ),
        items=(),
    )


def _procons_sunday_snapshot(*, cancelamento_label: str = "Label Qualquer") -> SundayBoardSnapshot:
    return SundayBoardSnapshot(
        board_id="82",
        name="Procons",
        columns=(
            SundayColumnSnapshot(
                id=PROCONS_CANCELAMENTO_SUNDAY_COLUMN,
                key="ouve_cancelamento_de_assinatura",
                label=cancelamento_label,
                type="status",
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
                id="610",
                key="status",
                label="Status",
                type="status",
                is_system=False,
            ),
        ),
        groups={"g_itens": "Itens"},
    )


def _ledger_record(monday_item_id: str, sunday_item_id: str) -> dict:
    return {
        "monday_board_id": "4944254220",
        "monday_item_id": monday_item_id,
        "sunday_board_id": "82",
        "sunday_item_id": sunday_item_id,
        "migration_status": "migrated",
        "migrated_at": "2026-08-12T18:00:00+00:00",
        "source_snapshot_timestamp": "2026-08-12T17:59:00+00:00",
    }


def test_cancelamento_maps_by_column_id_not_label():
    inventory = _procons_inventory()
    snapshot = _procons_sunday_snapshot(cancelamento_label="Rótulo Sunday Alterado")
    board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
    cancelamento_plan = next(
        plan
        for plan in board_plan.column_plans
        if plan.monday_column_id == PROCONS_CANCELAMENTO_MONDAY_COLUMN
    )
    assert cancelamento_plan.exists_in_target is True
    assert cancelamento_plan.sunday_column_id == PROCONS_CANCELAMENTO_SUNDAY_COLUMN
    mapping = get_explicit_column_mapping("4944254220", PROCONS_CANCELAMENTO_MONDAY_COLUMN)
    assert mapping is not None
    assert mapping.sunday_column_key == "ouve_cancelamento_de_assinatura"
    col = next(c for c in inventory.columns if c.id == PROCONS_CANCELAMENTO_MONDAY_COLUMN)
    assert (
        derive_expected_sunday_value(monday_column=col, source_text="Sim", board_plan=board_plan)
        == "sim"
    )
    assert (
        derive_expected_sunday_value(monday_column=col, source_text="Não", board_plan=board_plan)
        == "nao"
    )


def test_empty_source_is_skip_not_blocked():
    inventory = _procons_inventory()
    snapshot = _procons_sunday_snapshot()
    source = MondayApplySource(
        item_id="123",
        name="Item",
        group_id="g1",
        values_by_column_id={
            PROCONS_CANCELAMENTO_MONDAY_COLUMN: None,
            PROCONS_NOTIFICACAO_MONDAY_COLUMN: "https://drive.google.com/file/d/abc",
            PROCONS_DOCS_SAC_MONDAY_COLUMN: None,
        },
    )
    plan = build_repair_plan(
        monday_board_id="4944254220",
        sunday_board_id="82",
        inventory=inventory,
        sunday_snapshot=snapshot,
        apply_sources={"123": source},
        client=FakeSundayClient(values={}),
        ledger_records={"4944254220:123": _ledger_record("123", "9001")},
        item_ids=frozenset({"123"}),
        audit_completed_at="2026-08-13T01:21:00+00:00",
    )
    item = plan.items[0]
    assert item.skip_source_empty == 2
    assert item.blocked == 0
    assert item.notificacao_link_write is True
    assert plan.blocked == 0
    gate_ok, _ = evaluate_repair_gate(plan)
    assert gate_ok


def test_gislaine_repair_plan_two_writes_one_skip_zero_blocked():
    inventory = _procons_inventory()
    snapshot = _procons_sunday_snapshot()
    source = MondayApplySource(
        item_id="12315524808",
        name="Gislaine Assis de Lima",
        group_id="g1",
        values_by_column_id={
            PROCONS_CANCELAMENTO_MONDAY_COLUMN: "Sim",
            PROCONS_NOTIFICACAO_MONDAY_COLUMN: "https://drive.google.com/drive/folders/1abc",
            PROCONS_DOCS_SAC_MONDAY_COLUMN: None,
        },
    )
    plan = build_repair_plan(
        monday_board_id="4944254220",
        sunday_board_id="82",
        inventory=inventory,
        sunday_snapshot=snapshot,
        apply_sources={"12315524808": source},
        client=FakeSundayClient(values={}),
        ledger_records={"4944254220:12315524808": _ledger_record("12315524808", "7757")},
        item_ids=frozenset({"12315524808"}),
        audit_completed_at="2026-08-13T01:21:00+00:00",
    )
    item = plan.items[0]
    assert item.writes == 2
    assert item.skip_source_empty == 1
    assert item.blocked == 0
    assert plan.total_writes == 2


def test_item_10946636665_one_write_two_skips_zero_blocked():
    inventory = _procons_inventory()
    snapshot = _procons_sunday_snapshot()
    source = MondayApplySource(
        item_id="10946636665",
        name="Julia",
        group_id="g1",
        values_by_column_id={
            PROCONS_CANCELAMENTO_MONDAY_COLUMN: None,
            PROCONS_NOTIFICACAO_MONDAY_COLUMN: "https://drive.google.com/file/d/abc",
            PROCONS_DOCS_SAC_MONDAY_COLUMN: None,
        },
    )
    plan = build_repair_plan(
        monday_board_id="4944254220",
        sunday_board_id="82",
        inventory=inventory,
        sunday_snapshot=snapshot,
        apply_sources={"10946636665": source},
        client=FakeSundayClient(values={}),
        ledger_records={"4944254220:10946636665": _ledger_record("10946636665", "7759")},
        item_ids=frozenset({"10946636665"}),
        audit_completed_at="2026-08-13T01:21:00+00:00",
    )
    item = plan.items[0]
    assert item.writes == 1
    assert item.notificacao_link_write is True
    assert item.skip_source_empty == 2
    assert item.blocked == 0


def test_repair_gate_fails_when_source_changed_after_audit():
    inventory = _procons_inventory()
    snapshot = _procons_sunday_snapshot()
    source = MondayApplySource(
        item_id="123",
        name="Item",
        group_id="g1",
        values_by_column_id={PROCONS_CANCELAMENTO_MONDAY_COLUMN: "Não"},
    )
    plan = build_repair_plan(
        monday_board_id="4944254220",
        sunday_board_id="82",
        inventory=inventory,
        sunday_snapshot=snapshot,
        apply_sources={"123": source},
        client=FakeSundayClient(values={}),
        ledger_records={"4944254220:123": _ledger_record("123", "9001")},
        item_ids=frozenset({"123"}),
        audit_completed_at="2026-08-13T01:21:00+00:00",
        audit_source_values={"123": {PROCONS_CANCELAMENTO_MONDAY_COLUMN: "Sim"}},
    )
    assert plan.blocked == 1
    gate_ok, detail = evaluate_repair_gate(plan)
    assert not gate_ok
    assert "BLOCKED" in detail


def test_repair_counts_writes_and_skips_for_full_item():
    inventory = _procons_inventory()
    snapshot = _procons_sunday_snapshot()
    source = MondayApplySource(
        item_id="123",
        name="Item",
        group_id="g1",
        values_by_column_id={
            PROCONS_CANCELAMENTO_MONDAY_COLUMN: "Não",
            PROCONS_NOTIFICACAO_MONDAY_COLUMN: "https://drive.google.com/file/d/abc",
            PROCONS_DOCS_SAC_MONDAY_COLUMN: "https://drive.google.com/drive/folders/xyz",
        },
    )
    plan = build_repair_plan(
        monday_board_id="4944254220",
        sunday_board_id="82",
        inventory=inventory,
        sunday_snapshot=snapshot,
        apply_sources={"123": source},
        client=FakeSundayClient(values={}),
        ledger_records={"4944254220:123": _ledger_record("123", "9001")},
        item_ids=frozenset({"123"}),
        audit_completed_at="2026-08-13T01:21:00+00:00",
    )
    assert plan.total_writes == 3
    assert plan.skip_source_empty == 0
    assert plan.blocked == 0
    gate_ok, _ = evaluate_repair_gate(plan)
    assert gate_ok


def test_repair_skips_already_correct_fields():
    expected_link = derive_file_to_link_value(
        source_text="https://drive.google.com/file/d/abc",
        display_text="Notificação Procon",
    )
    inventory = _procons_inventory()
    snapshot = _procons_sunday_snapshot()
    source = MondayApplySource(
        item_id="123",
        name="Item",
        group_id="g1",
        values_by_column_id={
            PROCONS_CANCELAMENTO_MONDAY_COLUMN: "Sim",
            PROCONS_NOTIFICACAO_MONDAY_COLUMN: "https://drive.google.com/file/d/abc",
        },
    )
    plan = build_repair_plan(
        monday_board_id="4944254220",
        sunday_board_id="82",
        inventory=inventory,
        sunday_snapshot=snapshot,
        apply_sources={"123": source},
        client=FakeSundayClient(
            values={
                PROCONS_CANCELAMENTO_SUNDAY_COLUMN: "sim",
                "598": expected_link,
            },
        ),
        ledger_records={"4944254220:123": _ledger_record("123", "9001")},
        item_ids=frozenset({"123"}),
        audit_completed_at="2026-08-13T01:21:00+00:00",
    )
    assert plan.items_to_repair == 0
    assert plan.skip_already_correct == 2
    assert plan.blocked == 0


def test_repair_blocks_when_source_changed_after_audit_helper():
    assert should_block_field_for_source_change(
        audit_completed_at="2026-08-13T01:21:00+00:00",
        source_updated_at="2026-08-13T02:00:00+00:00",
        audited_source_value="Sim",
        live_source_value="Não",
    )


def test_repair_aborts_when_item_missing_from_ledger():
    inventory = _procons_inventory()
    snapshot = _procons_sunday_snapshot()
    try:
        build_repair_plan(
            monday_board_id="4944254220",
            sunday_board_id="82",
            inventory=inventory,
            sunday_snapshot=snapshot,
            apply_sources={},
            client=FakeSundayClient(values={}),
            ledger_records={},
            item_ids=frozenset({"999"}),
        )
    except RepairPlanAbort as exc:
        assert "999" in str(exc)
    else:
        raise AssertionError("expected RepairPlanAbort")


def test_repair_retry_is_idempotent():
    inventory = _procons_inventory()
    snapshot = _procons_sunday_snapshot()
    source = MondayApplySource(
        item_id="123",
        name="Item",
        group_id="g1",
        values_by_column_id={
            PROCONS_CANCELAMENTO_MONDAY_COLUMN: "Não",
            PROCONS_NOTIFICACAO_MONDAY_COLUMN: "https://drive.google.com/file/d/abc",
        },
    )
    client = FakeSundayClient(values={})
    ledger = {"4944254220:123": _ledger_record("123", "9001")}
    first = build_repair_plan(
        monday_board_id="4944254220",
        sunday_board_id="82",
        inventory=inventory,
        sunday_snapshot=snapshot,
        apply_sources={"123": source},
        client=client,
        ledger_records=ledger,
        item_ids=frozenset({"123"}),
        audit_completed_at="2026-08-13T01:21:00+00:00",
    )
    repaired_values = {
        PROCONS_CANCELAMENTO_SUNDAY_COLUMN: "nao",
        "598": derive_file_to_link_value(
            source_text="https://drive.google.com/file/d/abc",
            display_text="Notificação Procon",
        ),
    }
    second = build_repair_plan(
        monday_board_id="4944254220",
        sunday_board_id="82",
        inventory=inventory,
        sunday_snapshot=snapshot,
        apply_sources={"123": source},
        client=FakeSundayClient(values=repaired_values),
        ledger_records=ledger,
        item_ids=frozenset({"123"}),
        audit_completed_at="2026-08-13T01:21:00+00:00",
    )
    assert first.total_writes == 2
    assert second.total_writes == 0
    assert second.skip_already_correct == 2


def test_ten_item_aggregate_counts_with_three_skips():
    inventory = _procons_inventory()
    snapshot = _procons_sunday_snapshot()
    item_specs = {
        "12315524808": {
            "7757": {
                PROCONS_CANCELAMENTO_MONDAY_COLUMN: "Sim",
                PROCONS_NOTIFICACAO_MONDAY_COLUMN: "https://drive.google.com/d/a",
                PROCONS_DOCS_SAC_MONDAY_COLUMN: None,
            },
        },
        "10946636665": {
            "7759": {
                PROCONS_CANCELAMENTO_MONDAY_COLUMN: None,
                PROCONS_NOTIFICACAO_MONDAY_COLUMN: "https://drive.google.com/d/b",
                PROCONS_DOCS_SAC_MONDAY_COLUMN: None,
            },
        },
    }
    for index in range(8):
        mid = f"item{index}"
        item_specs[mid] = {
            f"s{index}": {
                PROCONS_CANCELAMENTO_MONDAY_COLUMN: "Não",
                PROCONS_NOTIFICACAO_MONDAY_COLUMN: f"https://drive.google.com/d/n{index}",
                PROCONS_DOCS_SAC_MONDAY_COLUMN: f"https://drive.google.com/d/d{index}",
            },
        }

    apply_sources = {}
    ledger = {}
    for mid, sid_values in item_specs.items():
        sid = next(iter(sid_values))
        values = sid_values[sid]
        apply_sources[mid] = MondayApplySource(
            item_id=mid,
            name="Item",
            group_id="g1",
            values_by_column_id=values,
        )
        ledger[f"4944254220:{mid}"] = _ledger_record(mid, sid)

    plan = build_repair_plan(
        monday_board_id="4944254220",
        sunday_board_id="82",
        inventory=inventory,
        sunday_snapshot=snapshot,
        apply_sources=apply_sources,
        client=FakeSundayClient(values={}),
        ledger_records=ledger,
        item_ids=frozenset(item_specs),
        audit_completed_at="2026-08-13T01:21:00+00:00",
    )
    assert plan.items_scope == 10
    assert plan.items_to_repair == 10
    assert plan.status_writes == 9
    assert plan.notificacao_link_writes == 10
    assert plan.docs_sac_link_writes == 8
    assert plan.total_writes == 27
    assert plan.skip_source_empty == 3
    assert plan.blocked == 0
    gate_ok, _ = evaluate_repair_gate(plan)
    assert gate_ok


def test_source_completeness_ok_for_procons_repair_mappings():
    inventory = _procons_inventory()
    snapshot = _procons_sunday_snapshot()
    board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
    source = MondayApplySource(
        item_id="12315524808",
        name="Gislaine",
        group_id="g1",
        values_by_column_id={
            PROCONS_CANCELAMENTO_MONDAY_COLUMN: "Sim",
            PROCONS_NOTIFICACAO_MONDAY_COLUMN: "https://drive.google.com/file/d/x",
            PROCONS_DOCS_SAC_MONDAY_COLUMN: "https://drive.google.com/drive/folders/y",
        },
    )
    report = check_source_completeness_for_sources(
        inventory=inventory,
        board_plan=board_plan,
        apply_sources={"12315524808": source},
    )
    assert report.ok


def test_link_values_equal_ignores_display_text_differences():
    left = {"url": "https://drive.google.com/file/d/abc", "text": "A"}
    right = {"url": "https://drive.google.com/file/d/abc", "text": "B"}
    assert link_values_equal(left, right)
