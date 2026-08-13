"""Testes do resolver canônico Monday semantic status → Sunday option key."""

from __future__ import annotations

import pytest

from classificacao_procons.migration.apply_writer import (
    MondayApplySource,
    _custom_status_write_value,
)
from classificacao_procons.migration.column_transforms import (
    PROCONS_CANCELAMENTO_MONDAY_COLUMN,
    PROCONS_CANCELAMENTO_SUNDAY_COLUMN,
    PROCONS_DOCS_SAC_MONDAY_COLUMN,
    PROCONS_NOTIFICACAO_MONDAY_COLUMN,
    PROCONS_NOTIFICACAO_SUNDAY_COLUMN,
    StatusResolveError,
    resolve_sunday_custom_status_option,
    resolve_sunday_custom_status_write_value,
    status_custom_values_equal,
)
from classificacao_procons.migration.mappings import build_board_plan, sunday_board_by_monday_map
from classificacao_procons.migration.models import (
    MondayBoardInventory,
    MondayColumnInfo,
    SundayBoardSnapshot,
    SundayColumnSnapshot,
)
from classificacao_procons.migration.repair_plan import build_repair_plan


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
        ),
        items=(),
    )


def _sunday_snapshot(*, options: list[dict]) -> SundayBoardSnapshot:
    return SundayBoardSnapshot(
        board_id="82",
        name="Procons",
        columns=(
            SundayColumnSnapshot(
                id=PROCONS_CANCELAMENTO_SUNDAY_COLUMN,
                key="ouve_cancelamento_de_assinatura",
                label="ouve Cancelamento de Assinatura?",
                type="status",
                is_system=False,
                settings={"options": options},
            ),
            SundayColumnSnapshot(
                id=PROCONS_NOTIFICACAO_SUNDAY_COLUMN,
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
        ),
        groups={"g_itens": "Itens"},
    )


PROCONS_LIVE_OPTIONS = [
    {"key": "opt_1", "color": "emerald", "label": "Não"},
    {"key": "opt_2", "color": "orange", "label": "Sim"},
]


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


def test_sim_resolves_to_live_sim_option():
    result = resolve_sunday_custom_status_option(
        column_options=PROCONS_LIVE_OPTIONS,
        semantic_key="sim",
        monday_label="Sim",
    )
    assert result.option_key == "opt_2"
    assert result.option_label == "Sim"
    assert result.method == "label_slug"


def test_nao_resolves_to_live_nao_option():
    result = resolve_sunday_custom_status_option(
        column_options=PROCONS_LIVE_OPTIONS,
        semantic_key="nao",
        monday_label="Não",
    )
    assert result.option_key == "opt_1"
    assert result.option_label == "Não"


def test_resolves_with_non_default_option_ids():
    options = [
        {"key": "yes_key", "label": "Sim", "color": "orange"},
        {"key": "no_key", "label": "Não", "color": "emerald"},
    ]
    assert resolve_sunday_custom_status_write_value(
        column_options=options,
        semantic_key="sim",
        monday_label="Sim",
    ) == "yes_key"
    assert resolve_sunday_custom_status_write_value(
        column_options=options,
        semantic_key="nao",
        monday_label="Não",
    ) == "no_key"


def test_resolves_when_sunday_label_changed_but_slug_still_matches():
    options = [
        {"key": "k_no", "label": "NAO", "color": "emerald"},
        {"key": "k_yes", "label": "SIM", "color": "orange"},
    ]
    result = resolve_sunday_custom_status_option(
        column_options=options,
        semantic_key="sim",
        monday_label="Sim",
    )
    assert result.option_key == "k_yes"
    assert result.method == "label_slug"


def test_unresolved_when_no_matching_option():
    with pytest.raises(StatusResolveError) as exc:
        resolve_sunday_custom_status_write_value(
            column_options=PROCONS_LIVE_OPTIONS,
            semantic_key="talvez",
            monday_label="Talvez",
        )
    assert exc.value.reason == "UNRESOLVED"


def test_unresolved_when_no_options():
    with pytest.raises(StatusResolveError) as exc:
        resolve_sunday_custom_status_write_value(
            column_options=[],
            semantic_key="sim",
            monday_label="Sim",
        )
    assert exc.value.reason == "UNRESOLVED"


def test_ambiguous_when_multiple_slug_matches():
    options = [
        {"key": "a", "label": "Sim", "color": "orange"},
        {"key": "b", "label": "SIM", "color": "orange"},
    ]
    with pytest.raises(StatusResolveError) as exc:
        resolve_sunday_custom_status_write_value(
            column_options=options,
            semantic_key="sim",
            monday_label="Sim",
        )
    assert exc.value.reason == "AMBIGUOUS"


def test_payload_uses_option_key_not_semantic_slug():
    payload_value = resolve_sunday_custom_status_write_value(
        column_options=PROCONS_LIVE_OPTIONS,
        semantic_key="sim",
        monday_label="Sim",
    )
    assert payload_value == "opt_2"
    assert payload_value != "sim"


def test_apply_writer_custom_status_uses_resolver():
    inventory = _procons_inventory()
    snapshot = _sunday_snapshot(options=PROCONS_LIVE_OPTIONS)
    board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
    monday_column = inventory.column_by_id(PROCONS_CANCELAMENTO_MONDAY_COLUMN)
    sunday_column = snapshot.columns[0]
    assert monday_column is not None
    assert _custom_status_write_value(
        monday_column=monday_column,
        source_text="Sim",
        board_plan=board_plan,
        sunday_column=sunday_column,
    ) == "opt_2"


def test_status_custom_values_equal_accepts_resolved_option_key():
    assert status_custom_values_equal(
        semantic_key="sim",
        actual_value="opt_2",
        column_options=PROCONS_LIVE_OPTIONS,
        monday_label="Sim",
    )


def test_repair_plan_idempotent_after_target_has_resolved_option():
    inventory = _procons_inventory()
    snapshot = _sunday_snapshot(options=PROCONS_LIVE_OPTIONS)
    source = MondayApplySource(
        item_id="12315524808",
        name="Gislaine",
        group_id="g1",
        values_by_column_id={
            PROCONS_CANCELAMENTO_MONDAY_COLUMN: "Sim",
            PROCONS_NOTIFICACAO_MONDAY_COLUMN: "https://drive.google.com/file/d/abc/view",
            PROCONS_DOCS_SAC_MONDAY_COLUMN: None,
        },
    )
    client = FakeSundayClient(
        values={
            PROCONS_CANCELAMENTO_SUNDAY_COLUMN: "opt_2",
            PROCONS_NOTIFICACAO_SUNDAY_COLUMN: {
                "url": "https://drive.google.com/file/d/abc/view",
                "text": "Notificação Procon",
            },
        },
    )
    plan = build_repair_plan(
        monday_board_id="4944254220",
        sunday_board_id="82",
        inventory=inventory,
        sunday_snapshot=snapshot,
        apply_sources={"12315524808": source},
        client=client,
        ledger_records={"4944254220:12315524808": _ledger_record("12315524808", "7757")},
        item_ids=frozenset({"12315524808"}),
        audit_completed_at="2026-08-13T01:21:00+00:00",
    )
    item = plan.items[0]
    assert item.cancelamento_write is False
    assert item.notificacao_link_write is False
    assert item.skip_already_correct == 2
    assert item.skip_source_empty == 1
    assert plan.total_writes == 0
