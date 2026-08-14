"""Testes do verifier canônico pós-APPLY."""

from __future__ import annotations

from classificacao_procons.migration.apply_writer import (
    expected_sunday_field_value,
    sunday_field_values_match,
)
from classificacao_procons.migration.column_transforms import link_values_equal
from classificacao_procons.migration.models import (
    BoardPlan,
    ColumnPlan,
    MondayColumnInfo,
    SundayColumnSnapshot,
)

PROCONS = "4944254220"


def _status_column() -> MondayColumnInfo:
    return MondayColumnInfo(id="status_main", title="Status", type="status")


def _sunday_status_column() -> SundayColumnSnapshot:
    return SundayColumnSnapshot(
        id="611",
        key="status_main",
        label="Status",
        type="status",
        is_system=False,
        settings={
            "options": [
                {"key": "opt_1", "label": "Não"},
                {"key": "opt_2", "label": "Sim"},
            ],
        },
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
        ),
        status_mappings={"status_main": {"Sim": "sim", "Não": "nao"}},
    )


def test_status_semantic_resolves_to_live_option_key_not_slug():
    expected = expected_sunday_field_value(
        monday_board_id=PROCONS,
        monday_column=_status_column(),
        source_text="Sim",
        board_plan=_board_plan(),
        sunday_column=_sunday_status_column(),
        plan_column=_board_plan().column_plans[0],
    )
    assert expected == "opt_2"
    assert expected != "sim"
    assert sunday_field_values_match(
        expected,
        "opt_2",
        monday_board_id=PROCONS,
        monday_column_id="status_main",
    )
    assert not sunday_field_values_match(
        "sim",
        "opt_2",
        monday_board_id=PROCONS,
        monday_column_id="status_main",
    )


def test_invalid_semantic_slug_is_not_accepted_as_target():
    expected = expected_sunday_field_value(
        monday_board_id=PROCONS,
        monday_column=_status_column(),
        source_text="Sim",
        board_plan=_board_plan(),
        sunday_column=_sunday_status_column(),
        plan_column=_board_plan().column_plans[0],
    )
    assert expected == "opt_2"
    assert not sunday_field_values_match(
        expected,
        "sim",
        monday_board_id=PROCONS,
        monday_column_id="status_main",
    )


def test_link_read_back_matches_by_url_not_display_text():
    expected = {"url": "https://example.test/doc.pdf", "text": "Docs SAC"}
    actual = {"url": "https://example.test/doc.pdf", "text": "Outro rótulo"}
    assert link_values_equal(expected, actual)
    assert sunday_field_values_match(
        expected,
        actual,
        monday_board_id=PROCONS,
        monday_column_id="arquivos8",
    )


def test_empty_source_field_is_not_expected_write():
    expected = expected_sunday_field_value(
        monday_board_id=PROCONS,
        monday_column=MondayColumnInfo(id="text_col", title="Obs", type="text"),
        source_text="",
        board_plan=BoardPlan(
            monday_board_id=PROCONS,
            monday_name="Procons",
            domain="procons",
            sunday_board_id="82",
            sunday_name="Procons Sunday",
            confidence="alta",
            column_plans=(
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
        ),
        sunday_column=SundayColumnSnapshot(
            id="700",
            key="text_col",
            label="Obs",
            type="text",
            is_system=False,
        ),
        plan_column=ColumnPlan(
            monday_column_id="text_col",
            monday_title="Obs",
            monday_type="text",
            strategy="direto",
            sunday_target="text_col",
            sunday_column_id="700",
            exists_in_target=True,
        ),
    )
    assert expected is None
