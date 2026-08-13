"""Testes da auditoria source → target."""

from __future__ import annotations

from classificacao_procons.migration.apply_writer import MondayApplySource
from classificacao_procons.migration.mappings import build_board_plan, sunday_board_by_monday_map
from classificacao_procons.migration.models import (
    MondayBoardInventory,
    MondayColumnInfo,
    SundayBoardSnapshot,
    SundayColumnSnapshot,
)
from classificacao_procons.migration.source_audit import (
    FieldAuditRow,
    ItemAuditResult,
    aggregate_board_metrics,
    audit_item_fields,
    build_mapping_matrix,
    classify_mapping_status,
    explain_legacy_field_checker,
)


class FakeSundayClient:
    def __init__(self, *, item_name: str, values: dict[str, object], status: str, group_id: str):
        self.item_name = item_name
        self.values = values
        self.status = status
        self.group_id = group_id

    def get_item(self, board_id: str, item_id: str):
        class Item:
            pass

        item = Item()
        item.name = self.item_name
        item.status = self.status
        item.group_id = self.group_id
        return item

    def get_value(self, item_id: str, column_id: str):
        return self.values.get(column_id)


def test_classify_unmapped_when_target_column_missing():
    inventory = MondayBoardInventory(
        board_id="4944254220",
        name="Procons",
        groups={"g1": "Pendentes"},
        columns=(MondayColumnInfo(id="txt", title="Origem", type="text"),),
        items=(),
    )
    board_plan = build_board_plan(
        inventory,
        SundayBoardSnapshot(board_id="82", name="Procons", columns=(), groups={}),
        sunday_board_by_monday_map(),
    )
    column_plan = board_plan.column_plans[0]
    status, _ = classify_mapping_status(column_plan)
    assert status == "UNMAPPED"


def test_legacy_checker_could_hide_missing_fields():
    info = explain_legacy_field_checker()
    assert info["could_produce_false_100_percent"] is True
    assert info["semantic_resolution_unverified_not_counted_as_verified"] is True
    assert "people" in info["skips_apply_writer_types"]


def test_audit_detects_missing_target_for_skipped_apply_writer_type():
    inventory = MondayBoardInventory(
        board_id="4944254220",
        name="Procons",
        groups={"g1": "Pendentes"},
        columns=(
            MondayColumnInfo(id="name", title="Name", type="name"),
            MondayColumnInfo(id="people", title="Responsavel", type="people"),
        ),
        items=(),
    )
    snapshot = SundayBoardSnapshot(
        board_id="82",
        name="Procons",
        columns=(
            SundayColumnSnapshot(
                id="sc_people",
                key=None,
                label="Responsavel",
                type="people",
                is_system=False,
            ),
        ),
        groups={"g_itens": "Itens"},
    )
    board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
    source = MondayApplySource(
        item_id="1",
        name="Item",
        group_id="g1",
        values_by_column_id={"people": "100"},
    )
    client = FakeSundayClient(
        item_name="Item",
        values={"sc_monday": "4944254220/1", "sc_people": None},
        status="to_do",
        group_id="g_itens",
    )
    result = audit_item_fields(
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=snapshot,
        source=source,
        sunday_item_id="9001",
        client=client,
        monday_id_column_id="sc_monday",
        target_group_id="g_itens",
    )
    people_rows = [row for row in result.fields if row.field_name == "Responsavel"]
    assert people_rows
    assert people_rows[0].result == "MISSING_TARGET_VALUE"


def test_aggregate_metrics_use_expected_mapped_denominator():
    metrics = aggregate_board_metrics(
        monday_board_id="4944254220",
        sunday_board_id="82",
        mapping_matrix=[],
        item_results=[
            ItemAuditResult(
                monday_item_id="1",
                sunday_item_id="9001",
                fields=[
                    FieldAuditRow(
                        monday_item_id="1",
                        sunday_item_id="9001",
                        monday_column_id="txt",
                        field_name="Origem",
                        mapping_status="MAPPED_DIRECT",
                        result="MATCH",
                    ),
                    FieldAuditRow(
                        monday_item_id="1",
                        sunday_item_id="9001",
                        monday_column_id="people",
                        field_name="Responsavel",
                        mapping_status="MAPPED_TRANSFORM",
                        result="MISSING_TARGET_VALUE",
                    ),
                ],
            ),
        ],
    )
    assert metrics.expected_mapped_fields == 2
    assert metrics.matched == 1
    assert metrics.missing_target_values == 1
    assert metrics.field_fidelity_rate == 0.5


def test_mapping_matrix_contains_status_column():
    inventory = MondayBoardInventory(
        board_id="5563754463",
        name="KPI",
        groups={"g1": "2023"},
        columns=(MondayColumnInfo(id="txt", title="Campo", type="text"),),
        items=(),
    )
    snapshot = SundayBoardSnapshot(
        board_id="86",
        name="KPI",
        columns=(
            SundayColumnSnapshot(
                id="sc1",
                key=None,
                label="Campo",
                type="text",
                is_system=False,
            ),
        ),
        groups={},
    )
    board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
    matrix = build_mapping_matrix(board_plan)
    assert matrix[0]["status"] == "MAPPED_DIRECT"
