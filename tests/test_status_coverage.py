"""Testes do guard e diagnóstico de custom status coverage."""

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
from classificacao_procons.migration.source_completeness import (
    check_source_completeness_for_sources,
)
from classificacao_procons.migration.status_coverage import (
    analyze_custom_status_coverage,
    check_status_coverage_for_sources,
    classify_status_source_vs_options,
    classify_target_live_state,
    diagnose_status_field,
    normalize_status_label_for_compare,
)

KPI_OPTIONS = [
    {"key": "opt_1", "label": "Em andamento", "color": "blue"},
    {"key": "opt_2", "label": "Improcedência", "color": "red"},
    {"key": "opt_3", "label": "Condenação", "color": "green"},
]

PROCONS_CAUSA1_OPTIONS = [
    {"key": "opt_5", "label": "roblemas com entrega", "color": "orange"},
    {"key": "opt_1", "label": "Problemas com Cancelamento", "color": "red"},
]


def _status_inventory(*, board_id: str, column_id: str, title: str) -> MondayBoardInventory:
    return MondayBoardInventory(
        board_id=board_id,
        name="Board",
        groups={"g1": "Grupo"},
        columns=(
            MondayColumnInfo(id="name", title="Name", type="name"),
            MondayColumnInfo(
                id=column_id,
                title=title,
                type="status",
                settings={"labels": {"0": title, "1": "Outro"}},
            ),
        ),
        items=(),
    )


def _status_snapshot(*, board_id: str, column_id: str, key: str, label: str, options: list[dict]):
    return SundayBoardSnapshot(
        board_id=board_id,
        name="Sunday",
        columns=(
            SundayColumnSnapshot(
                id=column_id,
                key=key,
                label=label,
                type="status",
                is_system=False,
                settings={"options": options},
            ),
        ),
        groups={"g_itens": "Itens"},
    )


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


def test_normalize_status_label_for_compare_strips_accents_and_case():
    left = normalize_status_label_for_compare("Em Recurso (Nosso)")
    right = normalize_status_label_for_compare("em recurso nosso")
    assert left == right


def test_exact_option_classification():
    result = classify_status_source_vs_options(
        source_value="Condenação",
        semantic_key="condenacao",
        column_options=KPI_OPTIONS,
        status_mappings={"Condenação": "condenacao"},
    )
    assert result.classification == "EXACT_OPTION"
    assert result.option_key == "opt_3"


def test_normalized_exact_option_classification():
    result = classify_status_source_vs_options(
        source_value="IMPROCEDÊNCIA",
        semantic_key="improcedencia",
        column_options=KPI_OPTIONS,
        status_mappings={},
    )
    assert result.classification == "NORMALIZED_EXACT_OPTION"
    assert result.option_key == "opt_2"


def test_target_option_missing_for_kpi_acordo():
    result = classify_status_source_vs_options(
        source_value="Acordo",
        semantic_key="acordo",
        column_options=KPI_OPTIONS,
        status_mappings={"Acordo": "acordo"},
    )
    assert result.classification == "TARGET_OPTION_MISSING"


def test_semantic_candidate_only_for_procons_typo_label():
    result = classify_status_source_vs_options(
        source_value="Problemas com entrega",
        semantic_key="problemas_com_entrega",
        column_options=PROCONS_CAUSA1_OPTIONS,
        status_mappings={"Problemas com entrega": "problemas_com_entrega"},
    )
    assert result.classification == "SEMANTIC_CANDIDATE_ONLY"
    assert result.candidate_label == "roblemas com entrega"


def test_ambiguous_when_multiple_exact_labels():
    options = [
        {"key": "a", "label": "Sim", "color": "orange"},
        {"key": "b", "label": "Sim", "color": "orange"},
    ]
    result = classify_status_source_vs_options(
        source_value="Sim",
        semantic_key="sim",
        column_options=options,
        status_mappings={},
    )
    assert result.classification == "AMBIGUOUS"


def test_target_live_indeterminate_when_slug_stored_without_option():
    state = classify_target_live_state(
        source_value="Acordo",
        semantic_key="acordo",
        target_current="acordo",
        column_options=KPI_OPTIONS,
        resolved_option_key=None,
    )
    assert state == "INDETERMINATE"


def test_target_live_correct_when_option_key_present():
    state = classify_target_live_state(
        source_value="Condenação",
        semantic_key="condenacao",
        target_current="opt_3",
        column_options=KPI_OPTIONS,
        resolved_option_key="opt_3",
    )
    assert state == "FIELD_VALUE_CORRECT"


def test_diagnose_status_field_unresolved_for_em_recurso():
    diag = diagnose_status_field(
        source_value="Em Recurso (Nosso)",
        semantic_key="em_recurso_nosso",
        column_options=KPI_OPTIONS,
        status_mappings={"Em Recurso (Nosso)": "em_recurso_nosso"},
        target_current="em_recurso_nosso",
    )
    assert diag.resolution == "UNRESOLVED"
    assert diag.classification == "TARGET_OPTION_MISSING"
    assert diag.target_live_state == "INDETERMINATE"


def test_status_coverage_guard_blocks_missing_option():
    inventory = _status_inventory(board_id="5563754463", column_id="status_11", title="Resultado")
    snapshot = _status_snapshot(
        board_id="86",
        column_id="569",
        key="resultado",
        label="Resultado",
        options=KPI_OPTIONS,
    )
    board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
    report = check_status_coverage_for_sources(
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=snapshot,
        apply_sources={
            "1": MondayApplySource(
                item_id="1",
                name="Item",
                group_id="g1",
                values_by_column_id={"status_11": "Acordo"},
            ),
        },
    )
    assert not report.ok
    assert report.issues[0].issue == "UNRESOLVED"


def test_status_coverage_guard_passes_for_resolvable_value():
    inventory = _status_inventory(board_id="5563754463", column_id="status_11", title="Resultado")
    snapshot = _status_snapshot(
        board_id="86",
        column_id="569",
        key="resultado",
        label="Resultado",
        options=KPI_OPTIONS,
    )
    board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
    report = check_status_coverage_for_sources(
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=snapshot,
        apply_sources={
            "1": MondayApplySource(
                item_id="1",
                name="Item",
                group_id="g1",
                values_by_column_id={"status_11": "Condenação"},
            ),
        },
    )
    assert report.ok


def test_source_completeness_includes_status_coverage_when_snapshot_provided():
    inventory = _status_inventory(board_id="5563754463", column_id="status_11", title="Resultado")
    snapshot = _status_snapshot(
        board_id="86",
        column_id="569",
        key="resultado",
        label="Resultado",
        options=KPI_OPTIONS,
    )
    board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
    report = check_source_completeness_for_sources(
        inventory=inventory,
        board_plan=board_plan,
        apply_sources={
            "1": MondayApplySource(
                item_id="1",
                name="Item",
                group_id="g1",
                values_by_column_id={"status_11": "Em Recurso (Nosso)"},
            ),
        },
        sunday_snapshot=snapshot,
    )
    assert not report.ok
    assert report.issues[-1].issue == "UNRESOLVED"


def test_analyze_custom_status_coverage_counts():
    inventory = _status_inventory(board_id="5563754463", column_id="status_11", title="Resultado")
    snapshot = _status_snapshot(
        board_id="86",
        column_id="569",
        key="resultado",
        label="Resultado",
        options=KPI_OPTIONS,
    )
    board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
    report = analyze_custom_status_coverage(
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=snapshot,
        apply_sources={
            "1": MondayApplySource(
                item_id="1",
                name="Item",
                group_id="g1",
                values_by_column_id={"status_11": "Acordo"},
            ),
            "2": MondayApplySource(
                item_id="2",
                name="Item 2",
                group_id="g1",
                values_by_column_id={"status_11": "Condenação"},
            ),
        },
    )
    assert report.distinct_source_values == 2
    assert report.resolved == 1
    assert report.unresolved == 1


def test_audit_marks_slug_target_as_semantic_resolution_unverified():
    inventory = _status_inventory(board_id="5563754463", column_id="status_11", title="Resultado")
    snapshot = _status_snapshot(
        board_id="86",
        column_id="569",
        key="resultado",
        label="Resultado",
        options=KPI_OPTIONS,
    )
    board_plan = build_board_plan(inventory, snapshot, sunday_board_by_monday_map())
    result = audit_item_fields(
        inventory=inventory,
        board_plan=board_plan,
        sunday_snapshot=snapshot,
        source=MondayApplySource(
            item_id="5563754498",
            name="Item",
            group_id="g1",
            values_by_column_id={"status_11": "Em Recurso (Nosso)"},
        ),
        sunday_item_id="7721",
        client=FakeSundayClient(
            values={"569": "em_recurso_nosso", "sc_monday": "5563754463/5563754498"},
        ),
        monday_id_column_id="sc_monday",
        target_group_id="g_itens",
    )
    status_rows = [row for row in result.fields if row.monday_column_id == "status_11"]
    assert status_rows
    assert status_rows[0].result == "SEMANTIC_RESOLUTION_UNVERIFIED"
    assert not result.is_fully_verified


def test_fully_verified_requires_no_semantic_unverified():
    inventory = _status_inventory(board_id="5563754463", column_id="status_11", title="Resultado")
    snapshot = _status_snapshot(
        board_id="86",
        column_id="569",
        key="resultado",
        label="Resultado",
        options=KPI_OPTIONS,
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
            values_by_column_id={"status_11": "Condenação"},
        ),
        sunday_item_id="9001",
        client=FakeSundayClient(values={"569": "opt_3", "sc_monday": "5563754463/1"}),
        monday_id_column_id="sc_monday",
        target_group_id="g_itens",
    )
    assert result.is_fully_verified
