"""Testes da Fase 2 — mapping e dry-run Monday → Sunday (sem nenhuma escrita)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from classificacao_procons.migration.dry_run import (
    DryRunReport,
    run_dry_run,
    select_recorte,
)
from classificacao_procons.migration.mappings import (
    build_column_plans,
    build_status_mappings,
    group_is_done,
    slugify_status_key,
    sunday_board_by_monday_map,
)
from classificacao_procons.migration.models import (
    LedgerRecord,
    MondayBoardInventory,
    MondayColumnInfo,
    MondayItemDigest,
    SundayBoardSnapshot,
    SundayColumnSnapshot,
)
from classificacao_procons.migration.monday_inventory import (
    inventory_from_payload,
    inventory_to_payload,
)
from classificacao_procons.migration.sunday_snapshot import snapshot_from_live_client

CUTOFF = datetime(2025, 8, 11, tzinfo=UTC)
RECENT = "2026-01-10T00:00:00Z"
OLD = "2023-05-01T00:00:00Z"


def _controle_inventory(items: tuple[MondayItemDigest, ...]) -> MondayBoardInventory:
    return MondayBoardInventory(
        board_id="5301515799",
        name="Controle Assinaturas Contratos",
        groups={"g_jan": "Contratos Pendentes de Assinatura Jan", "g_done": "Assinados"},
        columns=(
            MondayColumnInfo(id="name", title="Name", type="name"),
            MondayColumnInfo(
                id="status",
                title="Status",
                type="status",
                settings={"labels": {"0": "Aguardando Assinatura", "1": "Assinado"}},
            ),
            MondayColumnInfo(id="people", title="Pessoas", type="people"),
            MondayColumnInfo(id="rel", title="Contrato relacionado", type="board_relation"),
            MondayColumnInfo(id="files", title="Contrato", type="file"),
            MondayColumnInfo(id="formula1", title="Saving", type="formula"),
            MondayColumnInfo(id="loc", title="Local", type="location"),
        ),
        items=items,
    )


def _contratos_inventory(items: tuple[MondayItemDigest, ...]) -> MondayBoardInventory:
    return MondayBoardInventory(
        board_id="5385471914",
        name="Contratos",
        groups={"g1": "Contratos B4A"},
        columns=(
            MondayColumnInfo(id="name", title="Name", type="name"),
            MondayColumnInfo(
                id="vig",
                title="Vigência",
                type="status",
                settings={"labels": {"0": "Vigente", "1": "Não Vigente"}},
            ),
        ),
        items=items,
    )


def _sunday_target(with_relation_ok: bool) -> SundayBoardSnapshot:
    return SundayBoardSnapshot(
        board_id="77",
        name="Legal - Controle de Assinaturas - Jan & Luciano",
        columns=(
            SundayColumnSnapshot(
                id="428", key="name", label="Nome", type="text", is_system=True,
            ),
            SundayColumnSnapshot(
                id="900",
                key="contrato_relacionado",
                label="Contrato relacionado",
                type="board_relation",
                is_system=False,
                settings={"source_board_id": "88" if with_relation_ok else "79"},
            ),
        ),
        status_keys=("to_do", "follow_up", "done"),
    )


# ------------------------------------------------------------------- mappings


def test_should_map_wave1_boards_with_explicit_targets():
    board_map = sunday_board_by_monday_map()
    assert board_map["4443295406"] == "72"
    assert board_map["5301515799"] == "77"
    assert board_map["4944254220"] is None  # TARGET A CRIAR MANUALMENTE


def test_should_plan_columns_by_real_type_rules():
    inventory = _controle_inventory(())
    plans = {plan.monday_title: plan for plan in build_column_plans(inventory, None)}
    assert plans["Status"].strategy == "configurar_manualmente"
    assert plans["Pessoas"].strategy == "transformacao"
    assert plans["Contrato relacionado"].strategy == "transformacao"
    assert plans["Contrato"].strategy == "transformacao"  # file -> anexo por link
    assert plans["Saving"].strategy == "configurar_manualmente"  # formula
    assert plans["Local"].strategy == "transformacao"  # location -> text
    assert plans["Name"].strategy == "direto"


def test_should_detect_existing_target_column_by_label():
    inventory = _controle_inventory(())
    plans = build_column_plans(inventory, _sunday_target(with_relation_ok=True))
    by_title = {plan.monday_title: plan for plan in plans}
    assert by_title["Contrato relacionado"].exists_in_target is True
    assert by_title["Status"].exists_in_target is False


def test_should_build_status_mapping_with_deterministic_slugs():
    inventory = _controle_inventory(())
    mappings = build_status_mappings(inventory)
    assert mappings["status"]["Assinado"] == "assinado"
    assert mappings["status"]["Aguardando Assinatura"] == "aguardando_assinatura"
    assert slugify_status_key("Bloqueado - aguardando providencia") == (
        "bloqueado_aguardando_providencia"
    )


def test_should_flag_status_label_used_but_out_of_schema():
    item = MondayItemDigest(
        item_id="1",
        group_id="g_jan",
        created_at=RECENT,
        updated_at=RECENT,
        status_labels={"status": "Label Fantasma"},
    )
    mappings = build_status_mappings(_controle_inventory((item,)))
    assert mappings["status"]["Label Fantasma"] is None  # revisão explícita


def test_should_recognize_done_groups_including_year_archives():
    assert group_is_done("2024")
    assert group_is_done("Assinados")
    assert group_is_done("Processos Encerrados")
    assert not group_is_done("Pendente Fornecedor")


# -------------------------------------------------------------------- recorte


def test_should_keep_old_open_item_in_recorte():
    item = MondayItemDigest(
        item_id="1",
        group_id="g_jan",
        created_at=OLD,
        updated_at=OLD,
        status_labels={"status": "Aguardando Assinatura"},
    )
    selected, _done = select_recorte(_controle_inventory((item,)), cutoff=CUTOFF)
    assert "1" in selected  # aberto permanece mesmo com >12 meses


def test_should_skip_old_concluded_item():
    item = MondayItemDigest(
        item_id="2",
        group_id="g_done",
        created_at=OLD,
        updated_at=OLD,
        status_labels={"status": "Assinado"},
    )
    selected, _done = select_recorte(_controle_inventory((item,)), cutoff=CUTOFF)
    assert "2" not in selected


def test_should_keep_recent_concluded_item():
    item = MondayItemDigest(
        item_id="3",
        group_id="g_done",
        created_at=RECENT,
        updated_at=RECENT,
        status_labels={"status": "Assinado"},
    )
    selected, _done = select_recorte(_controle_inventory((item,)), cutoff=CUTOFF)
    assert "3" in selected


def test_should_use_vigencia_override_for_contratos_board():
    vigente_antigo = MondayItemDigest(
        item_id="10", group_id="g1", created_at=OLD, updated_at=OLD,
        status_labels={"vig": "Vigente"},
    )
    nao_vigente_antigo = MondayItemDigest(
        item_id="11", group_id="g1", created_at=OLD, updated_at=OLD,
        status_labels={"vig": "Não Vigente"},
    )
    selected, _done = select_recorte(
        _contratos_inventory((vigente_antigo, nao_vigente_antigo)), cutoff=CUTOFF,
    )
    assert "10" in selected
    assert "11" not in selected


# -------------------------------------------------------------------- dry-run


def _run(items, *, snapshot=None, users=None, scenario="pos_checklist"):
    inventories = {"5301515799": _controle_inventory(items)}
    snapshots = {"77": snapshot} if snapshot else {}
    return run_dry_run(
        inventories, snapshots, cutoff=CUTOFF, users_mapped=users or set(), scenario=scenario,
    )


def test_should_classify_ready_item():
    item = MondayItemDigest(
        item_id="1", group_id="g_jan", created_at=RECENT, updated_at=RECENT,
        status_labels={"status": "Aguardando Assinatura"},
    )
    report, _plans, _pulled = _run((item,))
    assert report.items[0].classification == "WAVE_1_READY"


def test_should_classify_manual_when_user_not_mapped():
    item = MondayItemDigest(
        item_id="1", group_id="g_jan", created_at=RECENT, updated_at=RECENT,
        people_ids=("777",),
    )
    report, _plans, _pulled = _run((item,))
    result = report.items[0]
    assert result.classification == "MANUAL"
    assert result.reasons == ("MISSING_USER_MAPPING",)

    report_ok, _plans, _pulled = _run((item,), users={"777"})
    assert report_ok.items[0].classification == "WAVE_1_READY"


def test_should_classify_wave2_historical_out_of_onda1():
    item = MondayItemDigest(
        item_id="1", group_id="g_done", created_at=OLD, updated_at=OLD,
        status_labels={"status": "Assinado"},
    )
    report, _plans, _pulled = _run((item,))
    result = report.items[0]
    # Fora da Onda 1 não é descarte: backfill obrigatório da Onda 2.
    assert result.classification == "WAVE_2_HISTORICAL"
    assert result.reasons == ("HISTORICAL_BACKFILL",)
    assert result.wave == "onda2"
    payload = report.to_payload()
    assert payload["onda2_backfill_obrigatorio"] == 1
    assert payload["meta_final"] == "1/1 itens no Sunday (duas ondas)"


def test_should_include_full_board_exception_in_wave1():
    from classificacao_procons.migration.models import MondayBoardInventory

    kpi = MondayBoardInventory(
        board_id="5563754463",
        name="KPI - Processos Consumidores",
        groups={"g2018": "2018"},
        columns=(),
        items=(
            MondayItemDigest(item_id="1", group_id="g2018", created_at=OLD, updated_at=OLD),
        ),
    )
    selected, _done = select_recorte(kpi, cutoff=CUTOFF)
    assert "1" in selected  # KPI integral na Onda 1 (exceção aprovada)


def test_should_error_on_group_without_explicit_rule():
    # Grupo desconhecido no board: NUNCA fallback silencioso para Itens.
    from classificacao_procons.migration.models import MondayBoardInventory

    inventory = MondayBoardInventory(
        board_id="5301515799",
        name="Controle",
        groups={"g_novo": "Grupo Surpresa Sem Regra"},
        columns=(),
        items=(
            MondayItemDigest(item_id="1", group_id="g_novo", created_at=RECENT,
                             updated_at=RECENT),
        ),
    )
    report, _plans, _pulled = run_dry_run({"5301515799": inventory}, {}, cutoff=CUTOFF)
    result = report.items[0]
    assert result.classification == "ERROR"
    assert "grupo_sem_regra_explicita" in result.flags


def test_should_have_explicit_rule_for_every_known_group():
    from classificacao_procons.migration.mappings import group_rule

    # Amostra das regras reais aprovadas (preservar/colapsar/transformar).
    assert group_rule("5301515799", "Assinados") == ("preservar", "terminal")
    assert group_rule("4944254220", "2024")[0] == "colapsar"
    assert group_rule("5385471914", "Contratos B2B")[0] == "transformar"
    assert group_rule("5385471914", "Contratos Encerrados")[1].startswith("Vigência")
    assert group_rule("5343921475", "Cível")[0] == "colapsar"
    assert group_rule("5301515799", "Grupo Inexistente") is None


def test_should_conserve_total_across_waves():
    open_item = MondayItemDigest(item_id="1", group_id="g_jan", created_at=RECENT,
                                 updated_at=RECENT)
    old_done = MondayItemDigest(item_id="2", group_id="g_done", created_at=OLD,
                                updated_at=OLD, status_labels={"status": "Assinado"})
    report, _plans, _pulled = _run((open_item, old_done))
    counts = report.counts()
    assert sum(counts.values()) == 2  # nenhum item some do escopo total
    assert counts["WAVE_1_READY"] == 1
    assert counts["WAVE_2_HISTORICAL"] == 1


def test_should_classify_error_when_relation_target_missing():
    item = MondayItemDigest(
        item_id="1", group_id="g_jan", created_at=RECENT, updated_at=RECENT,
        relation_targets={"rel": ("999999",)},  # alvo inexistente no inventário
    )
    report, _plans, _pulled = _run((item,))
    assert report.items[0].classification == "ERROR"


def test_should_flag_invalid_relation_config_in_estado_atual():
    item = MondayItemDigest(
        item_id="1", group_id="g_jan", created_at=RECENT, updated_at=RECENT,
        relation_targets={"rel": ("2",)},
    )
    target_ok = MondayItemDigest(
        item_id="2", group_id="g1", created_at=RECENT, updated_at=RECENT,
        status_labels={"vig": "Vigente"},
    )
    inventories = {
        "5301515799": _controle_inventory((item,)),
        "5385471914": _contratos_inventory((target_ok,)),
    }
    report, plans, _pulled = run_dry_run(
        inventories,
        {"77": _sunday_target(with_relation_ok=False)},
        cutoff=CUTOFF,
        scenario="estado_atual",
    )
    result = next(r for r in report.items if r.monday_item_id == "1")
    assert "INVALID_RELATION_CONFIG" in result.reasons
    relation = plans["5301515799"].relation_plans[0]
    assert relation.config_ok is False
    assert "CONFIGURAÇÃO MANUAL OBRIGATÓRIA" in (relation.note or "")


def test_should_pull_in_relation_target_outside_recorte():
    source = MondayItemDigest(
        item_id="1", group_id="g_jan", created_at=RECENT, updated_at=RECENT,
        relation_targets={"rel": ("50",)},
    )
    old_target = MondayItemDigest(
        item_id="50", group_id="g1", created_at=OLD, updated_at=OLD,
        status_labels={"vig": "Não Vigente"},  # fora do recorte por si só
    )
    inventories = {
        "5301515799": _controle_inventory((source,)),
        "5385471914": _contratos_inventory((old_target,)),
    }
    report, _plans, pulled = run_dry_run(inventories, {}, cutoff=CUTOFF)
    assert pulled == {"5385471914": 1}
    target_result = next(r for r in report.items if r.monday_item_id == "50")
    assert target_result.classification != "WAVE_2_HISTORICAL"


def test_should_aggregate_report_without_item_content():
    item = MondayItemDigest(
        item_id="1", group_id="g_jan", created_at=RECENT, updated_at=RECENT,
        file_count=2, has_updates=True,
    )
    report, _plans, _pulled = _run((item,))
    payload = report.to_payload()
    dumped = json.dumps(payload, ensure_ascii=False)
    assert payload["counts"]["WAVE_1_READY"] == 1
    assert payload["flags"]["file_materialization"] == 1
    # relatório agregado não carrega nomes/textos — só chaves técnicas.
    for forbidden in ("cpf", "name", "body", "consumidor"):
        assert forbidden not in dumped.lower()


# --------------------------------------------------- sanitização do inventário


def test_should_sanitize_inventory_digests_by_construction():
    item = MondayItemDigest(
        item_id="1", group_id="g_jan", created_at=RECENT, updated_at=RECENT,
        status_labels={"status": "Assinado"}, people_ids=("9",), file_count=1,
    )
    payload = inventory_to_payload(_controle_inventory((item,)))
    item_keys = set(payload["items"][0].keys())
    assert "name" not in item_keys
    assert "text" not in json.dumps(payload["items"]).lower().replace("long_text", "")
    restored = inventory_from_payload(payload)
    assert restored.items[0].status_labels == {"status": "Assinado"}
    assert restored.items[0].people_ids == ("9",)


# ------------------------------------------------------------ ledger / cache


def test_should_key_ledger_records_for_o1_idempotency():
    record = LedgerRecord(monday_board_id="5301515799", monday_item_id="123")
    assert record.key == "5301515799:123"
    ledger = {record.key: record}
    assert ledger["5301515799:123"].migration_status == "pending"


def test_should_report_counts_and_percentages():
    report = DryRunReport(cutoff_iso="2025-08-11", scenario="pos_checklist")
    assert report.to_payload()["onda1_total"] == 0  # vazio não divide por zero


# ------------------------------------------------- dry-run nunca escreve nada


class _ReadOnlySpyClient:
    """Client espião: leituras devolvem dados canned; escrita explode."""

    WRITE_METHODS = (
        "create_item",
        "update_item",
        "set_status",
        "set_custom_value",
        "set_relation",
        "add_comment",
        "add_link_attachment",
        "delete_item",
        "delete_comment",
        "create_group",
    )

    def __init__(self):
        self.read_calls: list[str] = []

    def __getattr__(self, name):
        if name in self.WRITE_METHODS:
            raise AssertionError(f"dry-run chamou método de escrita: {name}")
        raise AttributeError(name)

    def get_board(self, board_id):
        self.read_calls.append(f"get_board:{board_id}")
        from classificacao_procons.sunday.models import Board

        return Board.from_payload(
            {"id": board_id, "name": "X", "status_set": [{"key": "to_do", "label": "A"}]},
        )

    def list_columns(self, board_id):
        self.read_calls.append(f"list_columns:{board_id}")
        return []

    def list_groups(self, board_id):
        self.read_calls.append(f"list_groups:{board_id}")
        return []


def test_should_never_call_write_methods_in_dry_run_pipeline():
    spy = _ReadOnlySpyClient()
    snapshots = snapshot_from_live_client(spy, ["77"])
    item = MondayItemDigest(
        item_id="1", group_id="g_jan", created_at=RECENT, updated_at=RECENT,
    )
    report, _plans, _pulled = run_dry_run(
        {"5301515799": _controle_inventory((item,))}, snapshots, cutoff=CUTOFF,
    )
    assert report.counts()["WAVE_1_READY"] == 1
    assert spy.read_calls == ["get_board:77", "list_columns:77", "list_groups:77"]


@pytest.mark.parametrize("method", _ReadOnlySpyClient.WRITE_METHODS)
def test_should_explode_if_any_write_method_were_called(method):
    spy = _ReadOnlySpyClient()
    with pytest.raises(AssertionError, match="escrita"):
        getattr(spy, method)()
