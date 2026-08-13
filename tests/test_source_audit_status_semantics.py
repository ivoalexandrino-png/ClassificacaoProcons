"""Teste: status resolvível com slug no target continua MATCH."""

from __future__ import annotations

from classificacao_procons.migration.apply_writer import MondayApplySource
from classificacao_procons.migration.mappings import build_board_plan, sunday_board_by_monday_map
from classificacao_procons.migration.models import (
    MondayBoardInventory,
    MondayColumnInfo,
    SundayBoardSnapshot,
    SundayColumnSnapshot,
)
from classificacao_procons.migration.source_audit import audit_item_fields


class FakeSundayClient:
    def __init__(self, *, values: dict[str, object]):
        self.values = values

    def get_item(self, board_id: str, item_id: str):
        class Item:
            name = "Item"
            status = "to_do"
            group_id = "g_itens"

        return Item()

    def get_value(self, item_id: str, column_id: str):
        return self.values.get(column_id)


def test_resolved_status_slug_in_target_is_match_not_unverified():
    inventory = MondayBoardInventory(
        board_id="5563754463",
        name="KPI",
        groups={"g1": "Grupo"},
        columns=(
            MondayColumnInfo(id="name", title="Name", type="name"),
            MondayColumnInfo(id="status_11", title="Resultado", type="status"),
        ),
        items=(),
    )
    snapshot = SundayBoardSnapshot(
        board_id="86",
        name="KPI",
        columns=(
            SundayColumnSnapshot(
                id="569",
                key="resultado",
                label="Resultado",
                type="status",
                is_system=False,
                settings={
                    "options": [
                        {"key": "opt_2", "label": "Improcedência"},
                    ],
                },
            ),
        ),
        groups={"g_itens": "Itens"},
    )
    board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
    result = audit_item_fields(
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=snapshot,
        source=MondayApplySource(
            item_id="1",
            name="Item",
            group_id="g1",
            values_by_column_id={"status_11": "Improcedência"},
        ),
        sunday_item_id="7720",
        client=FakeSundayClient(values={"569": "improcedencia", "sc_monday": "5563754463/1"}),
        monday_id_column_id="sc_monday",
        target_group_id="g_itens",
    )
    status_rows = [row for row in result.fields if row.monday_column_id == "status_11"]
    assert status_rows[0].result == "MATCH"
    assert result.is_fully_verified
