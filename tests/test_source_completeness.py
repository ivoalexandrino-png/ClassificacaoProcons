"""Testes do guard global de completude source → mapping."""

from __future__ import annotations

from classificacao_procons.migration.apply_writer import MondayApplySource
from classificacao_procons.migration.mappings import build_board_plan, sunday_board_by_monday_map
from classificacao_procons.migration.models import (
    MondayBoardInventory,
    MondayColumnInfo,
    SundayBoardSnapshot,
    SundayColumnSnapshot,
)
from classificacao_procons.migration.source_completeness import (
    check_source_completeness_for_sources,
)


def _inventory_with_text_column() -> MondayBoardInventory:
    return MondayBoardInventory(
        board_id="5563754463",
        name="KPI",
        groups={"g1": "2023"},
        columns=(
            MondayColumnInfo(id="name", title="Name", type="name"),
            MondayColumnInfo(id="txt", title="Campo KPI", type="text"),
            MondayColumnInfo(id="people", title="Responsavel", type="people"),
        ),
        items=(),
    )


def _sunday_snapshot_with_text() -> SundayBoardSnapshot:
    return SundayBoardSnapshot(
        board_id="86",
        name="KPI Sunday",
        columns=(
            SundayColumnSnapshot(
                id="sc_txt",
                key=None,
                label="Campo KPI",
                type="text",
                is_system=False,
            ),
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


def test_filled_source_without_mapping_target_fails():
    inventory = _inventory_with_text_column()
    target = SundayBoardSnapshot(board_id="86", name="KPI Sunday", columns=(), groups={})
    board_plan = build_board_plan(inventory, target, sunday_board_by_monday_map())
    report = check_source_completeness_for_sources(
        inventory=inventory,
        board_plan=board_plan,
        apply_sources={
            "1": MondayApplySource(
                item_id="1",
                name="Item",
                group_id="g1",
                values_by_column_id={"txt": "valor"},
            ),
        },
    )
    assert not report.ok
    assert report.issues[0].issue == "UNMAPPED"


def test_mapped_field_with_empty_source_is_ok():
    inventory = _inventory_with_text_column()
    target = _sunday_snapshot_with_text()
    board_plan = build_board_plan(inventory, target, sunday_board_by_monday_map())
    report = check_source_completeness_for_sources(
        inventory=inventory,
        board_plan=board_plan,
        apply_sources={
            "1": MondayApplySource(
                item_id="1",
                name="Item",
                group_id="g1",
                values_by_column_id={"txt": None},
            ),
        },
    )
    assert report.ok


def test_mapped_direct_field_passes():
    inventory = _inventory_with_text_column()
    target = _sunday_snapshot_with_text()
    board_plan = build_board_plan(inventory, target, sunday_board_by_monday_map())
    report = check_source_completeness_for_sources(
        inventory=inventory,
        board_plan=board_plan,
        apply_sources={
            "1": MondayApplySource(
                item_id="1",
                name="Item",
                group_id="g1",
                values_by_column_id={"txt": "valor"},
            ),
        },
    )
    assert report.ok


def test_apply_writer_skip_type_with_source_fails():
    inventory = _inventory_with_text_column()
    target = _sunday_snapshot_with_text()
    board_plan = build_board_plan(inventory, target, sunday_board_by_monday_map())
    report = check_source_completeness_for_sources(
        inventory=inventory,
        board_plan=board_plan,
        apply_sources={
            "1": MondayApplySource(
                item_id="1",
                name="Item",
                group_id="g1",
                values_by_column_id={"people": "100"},
            ),
        },
    )
    assert not report.ok
    assert report.issues[0].issue == "MAPPED_BUT_NOT_WRITABLE"


def test_intentionally_not_migrated_requires_reason():
    inventory = MondayBoardInventory(
        board_id="5563754463",
        name="KPI",
        groups={"g1": "2023"},
        columns=(
            MondayColumnInfo(id="meta", title="Item ID", type="item_id"),
        ),
        items=(),
    )
    target = SundayBoardSnapshot(board_id="86", name="KPI Sunday", columns=(), groups={})
    board_plan = build_board_plan(inventory, target, sunday_board_by_monday_map())
    report = check_source_completeness_for_sources(
        inventory=inventory,
        board_plan=board_plan,
        apply_sources={
            "1": MondayApplySource(
                item_id="1",
                name="Item",
                group_id="g1",
                values_by_column_id={"meta": "123"},
            ),
        },
    )
    assert report.ok


def test_new_source_column_without_plan_fails():
    inventory = MondayBoardInventory(
        board_id="4944254220",
        name="Procons",
        groups={"g1": "Pendentes"},
        columns=(
            MondayColumnInfo(id="nova", title="Coluna Nova", type="text"),
        ),
        items=(),
    )
    target = SundayBoardSnapshot(board_id="82", name="Procons Sunday", columns=(), groups={})
    board_plan = build_board_plan(inventory, target, sunday_board_by_monday_map())
    report = check_source_completeness_for_sources(
        inventory=inventory,
        board_plan=board_plan,
        apply_sources={
            "1": MondayApplySource(
                item_id="1",
                name="Item",
                group_id="g1",
                values_by_column_id={"nova": "x"},
            ),
        },
    )
    assert not report.ok


def test_kpi_trabalhista_procons_board_plans_are_supported():
    for board_id in ("5563754463", "4443297481", "4944254220"):
        inventory = MondayBoardInventory(
            board_id=board_id,
            name=board_id,
            groups={"g1": "Grupo"},
            columns=(MondayColumnInfo(id="name", title="Name", type="name"),),
            items=(),
        )
        sunday_id = {"5563754463": "86", "4443297481": "85", "4944254220": "82"}[board_id]
        target = SundayBoardSnapshot(board_id=sunday_id, name="x", columns=(), groups={})
        board_plan = build_board_plan(inventory, target, sunday_board_by_monday_map())
        report = check_source_completeness_for_sources(
            inventory=inventory,
            board_plan=board_plan,
            apply_sources={
                "1": MondayApplySource(
                    item_id="1",
                    name="Item",
                    group_id="g1",
                    values_by_column_id={},
                ),
            },
        )
        assert report.ok
