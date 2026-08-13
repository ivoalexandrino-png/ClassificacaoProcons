"""Testes do repair scope6 (6 custom statuses)."""

from __future__ import annotations

import pytest

from classificacao_procons.migration.apply_writer import MondayApplySource
from classificacao_procons.migration.models import (
    MondayBoardInventory,
    MondayColumnInfo,
    SundayBoardSnapshot,
    SundayColumnSnapshot,
)
from classificacao_procons.migration.status_repair_scope6 import (
    SCOPE6_ENTRIES,
    StatusRepairScope6Abort,
    _operation_for_target,
    apply_scope6_repair_plan,
    build_scope6_repair_plan,
    validate_scope6_pre_repair_plan,
)

KPI_OPTIONS = [
    {"key": "opt_1", "label": "Em andamento"},
    {"key": "opt_2", "label": "Improcedência"},
    {"key": "opt_3", "label": "Condenação"},
    {"key": "opt_4", "label": "Acordo"},
    {"key": "opt_5", "label": "Em Recurso (Nosso)"},
]

PROCONS_OPTIONS = [
    {"key": "opt_5", "label": "Problemas com entrega"},
]


class FakeSundayClient:
    def __init__(self, *, values: dict[tuple[str, str], object]):
        self.values = values
        self.writes: list[tuple[str, str, str, object]] = []

    def get_value(self, item_id: str, column_id: str):
        return self.values.get((item_id, column_id))

    def set_custom_value(
        self,
        board_id: str,
        item_id: str,
        column_id: str,
        value: object,
        *,
        verify: bool = False,
    ):
        self.writes.append((board_id, item_id, column_id, value))
        self.values[(item_id, column_id)] = value
        if verify and self.values[(item_id, column_id)] != value:
            raise RuntimeError("verify failed")


def _inventory(board_id: str) -> MondayBoardInventory:
    return MondayBoardInventory(
        board_id=board_id,
        name=board_id,
        groups={"g1": "Grupo"},
        columns=(MondayColumnInfo(id="status_11", title="Status", type="status"),),
        items=(),
    )


def _snapshots() -> dict[str, SundayBoardSnapshot]:
    return {
        "86": SundayBoardSnapshot(
            board_id="86",
            name="KPI",
            columns=(
                SundayColumnSnapshot(
                    id="569",
                    key="resultado",
                    label="Resultado",
                    type="status",
                    is_system=False,
                    settings={"options": KPI_OPTIONS},
                ),
            ),
            groups={},
        ),
        "82": SundayBoardSnapshot(
            board_id="82",
            name="Procons",
            columns=(
                SundayColumnSnapshot(
                    id="611",
                    key="causa_1",
                    label="Causa 1",
                    type="status",
                    is_system=False,
                    settings={"options": PROCONS_OPTIONS},
                ),
            ),
            groups={},
        ),
    }


def _sources() -> dict[str, dict[str, MondayApplySource]]:
    kpi_sources = {}
    for entry in SCOPE6_ENTRIES:
        if entry.monday_board_id != "5563754463":
            continue
        kpi_sources[entry.monday_item_id] = MondayApplySource(
            item_id=entry.monday_item_id,
            name="Item",
            group_id="g1",
            values_by_column_id={"status_11": entry.audited_source_value},
        )
    procons = SCOPE6_ENTRIES[-1]
    return {
        "5563754463": kpi_sources,
        "4944254220": {
            procons.monday_item_id: MondayApplySource(
                item_id=procons.monday_item_id,
                name="Item",
                group_id="g1",
                values_by_column_id={"status_11": procons.audited_source_value},
            ),
        },
    }


def test_slug_legacy_is_write_required_not_skip():
    assert _operation_for_target(target_current="acordo", option_key="opt_4") == "status_write"
    assert (
        _operation_for_target(target_current="em_recurso_nosso", option_key="opt_5")
        == "status_write"
    )
    assert (
        _operation_for_target(target_current="problemas_com_entrega", option_key="opt_5")
        == "status_write"
    )


def test_option_key_is_skip_already_correct():
    assert (
        _operation_for_target(target_current="opt_4", option_key="opt_4")
        == "skip_already_correct"
    )


def test_pre_repair_plan_expects_six_writes_for_legacy_slugs():
    values = {
        ("7721", "569"): "em_recurso_nosso",
        ("7722", "569"): "em_recurso_nosso",
        ("7724", "569"): "em_recurso_nosso",
        ("7741", "569"): "acordo",
        ("7726", "569"): "acordo",
        ("7762", "611"): "problemas_com_entrega",
    }
    client = FakeSundayClient(values=values)
    plan = build_scope6_repair_plan(
        snapshots=_snapshots(),
        apply_sources=_sources(),
        inventories={
            "5563754463": _inventory("5563754463"),
            "4944254220": _inventory("4944254220"),
        },
        client=client,
    )
    assert plan.items_scope == 6
    assert plan.status_writes == 6
    assert plan.skip_already_correct == 0
    assert plan.blocked == 0
    validate_scope6_pre_repair_plan(plan)


def test_apply_writes_option_keys_only():
    values = {
        ("7721", "569"): "em_recurso_nosso",
        ("7722", "569"): "em_recurso_nosso",
        ("7724", "569"): "em_recurso_nosso",
        ("7741", "569"): "acordo",
        ("7726", "569"): "acordo",
        ("7762", "611"): "problemas_com_entrega",
    }
    client = FakeSundayClient(values=values)
    plan = build_scope6_repair_plan(
        snapshots=_snapshots(),
        apply_sources=_sources(),
        inventories={
            "5563754463": _inventory("5563754463"),
            "4944254220": _inventory("4944254220"),
        },
        client=client,
    )
    result = apply_scope6_repair_plan(plan=plan, client=client)
    assert result.writes_succeeded == 6
    assert result.write_checks_ok == 6
    assert all(write[3] in {"opt_4", "opt_5"} for write in client.writes)
    assert "acordo" not in {str(write[3]) for write in client.writes}


def test_idempotent_plan_after_option_keys_written():
    values = {
        ("7721", "569"): "opt_5",
        ("7722", "569"): "opt_5",
        ("7724", "569"): "opt_5",
        ("7741", "569"): "opt_4",
        ("7726", "569"): "opt_4",
        ("7762", "611"): "opt_5",
    }
    client = FakeSundayClient(values=values)
    plan = build_scope6_repair_plan(
        snapshots=_snapshots(),
        apply_sources=_sources(),
        inventories={
            "5563754463": _inventory("5563754463"),
            "4944254220": _inventory("4944254220"),
        },
        client=client,
    )
    assert plan.status_writes == 0
    assert plan.skip_already_correct == 6
    with pytest.raises(StatusRepairScope6Abort):
        validate_scope6_pre_repair_plan(plan)
