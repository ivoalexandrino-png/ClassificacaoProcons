"""Testes do repair PLAN e overrides de coluna Procons."""

from __future__ import annotations

from classificacao_procons.migration.apply_writer import MondayApplySource
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
    classify_item_temporal,
)
from classificacao_procons.migration.source_audit import derive_expected_sunday_value


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
                id="color_mknz9dwg",
                title="Houve Cancelamento de Assinatura?",
                type="status",
                settings={"labels": {"0": "Não", "1": "Sim"}},
            ),
            MondayColumnInfo(id="arquivos", title="Notificação Procon", type="file"),
            MondayColumnInfo(id="arquivos8", title="Docs SAC", type="file"),
            MondayColumnInfo(id="status8", title="Status", type="status"),
        ),
        items=(),
    )


def _procons_sunday_snapshot() -> SundayBoardSnapshot:
    return SundayBoardSnapshot(
        board_id="82",
        name="Procons",
        columns=(
            SundayColumnSnapshot(
                id="609",
                key="ouve_cancelamento_de_assinatura",
                label="ouve Cancelamento de Assinatura?",
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
            SundayColumnSnapshot(
                id="595",
                key="monday_id",
                label="Monday ID",
                type="text",
                is_system=False,
            ),
        ),
        groups={"g_itens": "Itens"},
    )


def test_cancelamento_sim_nao_maps_via_label_override():
    inventory = _procons_inventory()
    snapshot = _procons_sunday_snapshot()
    board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
    cancelamento_plan = next(
        plan for plan in board_plan.column_plans if plan.monday_column_id == "color_mknz9dwg"
    )
    assert cancelamento_plan.exists_in_target is True
    assert cancelamento_plan.sunday_column_id == "609"
    col = next(c for c in inventory.columns if c.id == "color_mknz9dwg")
    assert derive_expected_sunday_value(
        monday_column=col,
        source_text="Sim",
        board_plan=board_plan,
    ) == "sim"
    assert derive_expected_sunday_value(
        monday_column=col,
        source_text="Não",
        board_plan=board_plan,
    ) == "nao"


def test_repair_plan_skips_fields_already_correct():
    inventory = _procons_inventory()
    snapshot = _procons_sunday_snapshot()
    source = MondayApplySource(
        item_id="123",
        name="Item",
        group_id="g1",
        values_by_column_id={
            "status8": "Respondido",
            "color_mknz9dwg": "Sim",
        },
    )
    client = FakeSundayClient(
        values={
            "595": "4944254220/123",
            "610": "respondido",
            "609": "sim",
        },
    )
    ledger = {
        "4944254220:123": {
            "monday_board_id": "4944254220",
            "monday_item_id": "123",
            "sunday_board_id": "82",
            "sunday_item_id": "9001",
            "migration_status": "migrated",
            "migrated_at": "2026-08-12T18:00:00+00:00",
            "source_snapshot_timestamp": "2026-08-12T17:59:00+00:00",
        },
    }
    plan = build_repair_plan(
        monday_board_id="4944254220",
        sunday_board_id="82",
        inventory=inventory,
        sunday_snapshot=snapshot,
        apply_sources={"123": source},
        client=client,
        monday_id_column_id="595",
        target_group_id="g_itens",
        ledger_records=ledger,
    )
    assert plan.items_to_repair == 0
    assert plan.field_writes == 0


def test_repair_plan_includes_missing_file_and_status_fields():
    inventory = _procons_inventory()
    snapshot = _procons_sunday_snapshot()
    source = MondayApplySource(
        item_id="123",
        name="Item",
        group_id="g1",
        values_by_column_id={
            "color_mknz9dwg": "Não",
            "arquivos": "https://drive.google.com/file/d/abc",
            "arquivos8": "https://drive.google.com/drive/folders/xyz",
        },
    )
    client = FakeSundayClient(values={"595": "4944254220/123"})
    ledger = {
        "4944254220:123": {
            "monday_board_id": "4944254220",
            "monday_item_id": "123",
            "sunday_board_id": "82",
            "sunday_item_id": "9001",
            "migration_status": "migrated",
            "migrated_at": "2026-08-12T18:00:00+00:00",
            "source_snapshot_timestamp": "2026-08-12T17:59:00+00:00",
        },
    }
    plan = build_repair_plan(
        monday_board_id="4944254220",
        sunday_board_id="82",
        inventory=inventory,
        sunday_snapshot=snapshot,
        apply_sources={"123": source},
        client=client,
        monday_id_column_id="595",
        target_group_id="g_itens",
        ledger_records=ledger,
    )
    assert plan.items_to_repair == 1
    assert plan.field_writes == 1
    assert plan.file_links == 2
    field_names = {op.field_name for op in plan.items[0].fields_to_repair}
    assert "Houve Cancelamento de Assinatura?" in field_names
    assert "Notificação Procon" in field_names
    assert "Docs SAC" in field_names


def test_repair_plan_aborts_when_item_missing_from_ledger():
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
            monday_id_column_id="595",
            target_group_id="g_itens",
            ledger_records={},
            item_ids=frozenset({"999"}),
        )
    except RepairPlanAbort as exc:
        assert "999" in str(exc)
    else:
        raise AssertionError("expected RepairPlanAbort")


def test_classify_item_temporal_post_migration_delta():
    result = classify_item_temporal(
        migrated_at="2026-08-12T18:00:00+00:00",
        source_snapshot_timestamp="2026-08-12T17:59:00+00:00",
        source_updated_at="2026-08-12T22:00:00+00:00",
    )
    assert result == "POST_MIGRATION_DELTA"


def test_classify_item_temporal_migration_defect():
    result = classify_item_temporal(
        migrated_at="2026-08-12T18:00:00+00:00",
        source_snapshot_timestamp="2026-08-12T17:59:00+00:00",
        source_updated_at="2026-08-12T17:58:00+00:00",
    )
    assert result == "MIGRATION_DEFECT"
