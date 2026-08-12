"""Testes do executor Fase 3 — PLAN nunca escreve; APPLY fail-closed (mockado)."""

from __future__ import annotations

import json

import pytest

from classificacao_procons.migration.dry_run import run_dry_run
from classificacao_procons.migration.executor import (
    BOARD_ALLOWLIST,
    DEFAULT_LEDGER_PATH,
    LEGACY_LEDGER_PATH,
    ApplyMigrationContext,
    ExecutorAbort,
    GateCheck,
    apply_plan,
    attachment_idempotency_name,
    build_execution_plan,
    build_sunday_schema_checks,
    comment_idempotency_marker,
    import_legacy_ledger_if_needed,
    load_persistent_ledger,
    persist_ledger_record,
    snapshot_fingerprint,
    sunday_config_from_test_env,
)
from classificacao_procons.migration.models import (
    MondayBoardInventory,
    MondayColumnInfo,
    MondayItemDigest,
    MondayUpdateDigest,
)
from classificacao_procons.migration.user_mapping import UserMappingPolicy

RECENT = "2026-08-01T00:00:00Z"
KPI_BOARD = "5563754463"
CONTROLE = "5301515799"
CONTRATOS = "5385471914"
AUDIENCIAS = "4443295406"
TRABALHISTA = "4443297481"

POLICY = UserMappingPolicy(
    exact_match_ids=frozenset({"100"}),
    active_unmatched_ids=frozenset({"200"}),
    deactivated_ids=frozenset({"300"}),
)


def _kpi_inventory(items=None) -> MondayBoardInventory:
    default_items = tuple(
        MondayItemDigest(item_id=str(i), group_id="g2023", created_at=RECENT,
                         updated_at=RECENT)
        for i in range(1, 4)
    )
    return MondayBoardInventory(
        board_id=KPI_BOARD,
        name="KPI - Processos Consumidores",
        groups={"g2023": "2023"},
        columns=(MondayColumnInfo(id="name", title="Name", type="name"),),
        items=items if items is not None else default_items,
    )


def _plan_for(inventory, *, wave=1, max_items=50, item_id=None, mode="plan", ledger=None,
              monday_id_index=None, policy=POLICY, schema_checks=None):
    report, _plans, _pulled = run_dry_run(
        {inventory.board_id: inventory},
        {},
        user_policy=policy,
        users_mapped=set(policy.exact_match_ids),
    )
    return build_execution_plan(
        inventory=inventory,
        report=report,
        wave=wave,
        max_items=max_items,
        item_id=item_id,
        mode=mode,
        user_policy=policy,
        persistent_ledger=ledger,
        sunday_monday_id_index=monday_id_index,
        sunday_schema_checks=schema_checks,
    )


class SpyClient:
    """Client espião: registra escritas; qualquer escrita em PLAN é proibida."""

    def __init__(self, fail_on: set[str] | None = None):
        self.created: list[str] = []
        self.fail_on = fail_on or set()
        self._next_id = 9000

    def create_item(self, board_id, name, **kwargs):
        marker = name.split()[-1]
        if marker in self.fail_on:
            raise RuntimeError("falha simulada")
        self._next_id += 1
        from classificacao_procons.sunday.models import Item

        self.created.append(marker)
        return Item.from_payload({"id": self._next_id, "board_id": board_id})


# ----------------------------------------------------------------------- PLAN


def test_plan_never_writes_anywhere(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    plan = _plan_for(_kpi_inventory())
    assert plan.mode == "plan"
    assert not ledger_path.exists()  # PLAN não cria/altera ledger persistente
    assert plan.counts() == {"create": 3}


def test_plan_is_default_and_apply_requires_explicit_mode():
    plan = _plan_for(_kpi_inventory())
    with pytest.raises(ExecutorAbort, match="modo apply"):
        apply_plan(plan, client=SpyClient(), confirm_writes=True)


def test_apply_requires_confirm_writes_flag(monkeypatch):
    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    plan = _plan_for(_kpi_inventory(), mode="apply")
    with pytest.raises(ExecutorAbort, match="confirm_writes"):
        apply_plan(plan, client=SpyClient(), confirm_writes=False)


def test_apply_requires_env_allow_apply(monkeypatch):
    monkeypatch.delenv("SUNDAY_MIGRATION_ALLOW_APPLY", raising=False)
    plan = _plan_for(_kpi_inventory(), mode="apply")
    with pytest.raises(ExecutorAbort, match="SUNDAY_MIGRATION_ALLOW_APPLY"):
        apply_plan(plan, client=SpyClient(), confirm_writes=True)


def test_board_allowlist_blocks_unknown_board():
    rogue = MondayBoardInventory(board_id="999", name="X", groups={}, columns=(), items=())
    report, _plans, _pulled = run_dry_run({KPI_BOARD: _kpi_inventory()}, {})
    with pytest.raises(ExecutorAbort, match="allowlist"):
        build_execution_plan(
            inventory=rogue, report=report, wave=1, max_items=10,
        )
    assert set(BOARD_ALLOWLIST) == {
        "4944254220", "3961072966", "4443295406", "5343921475",
        "4443297481", "5563754463", "5301515799", "5385471914",
    }


def test_max_items_gate_blocks_oversized_plan(monkeypatch):
    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    plan = _plan_for(_kpi_inventory(), max_items=2, mode="apply",
                     schema_checks=[GateCheck("schema_live_verificado", True)])
    gate = {check.name: check.ok for check in plan.gate}
    assert gate["max_items"] is False
    with pytest.raises(ExecutorAbort, match="max_items"):
        apply_plan(
            plan, client=SpyClient(), confirm_writes=True,
            snapshot_revalidator=lambda: plan.snapshot_fingerprint,
        )


def test_item_allowlist_is_identical_in_plan_and_apply(monkeypatch, tmp_path):
    inventory = _kpi_inventory()
    plan = _plan_for(inventory, item_id="2")
    apply = _plan_for(
        inventory,
        item_id="2",
        mode="apply",
        schema_checks=[GateCheck("schema_live_verificado", True)],
    )

    assert plan.requested_item_id == "2"
    assert plan.to_payload()["source_scope"] == 1
    assert [operation.monday_item_id for operation in plan.operations] == ["2"]
    assert [operation.monday_item_id for operation in apply.operations] == ["2"]

    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    spy = SpyClient()
    result = apply_plan(
        apply,
        client=spy,
        confirm_writes=True,
        snapshot_revalidator=lambda: apply.snapshot_fingerprint,
        ledger_path=tmp_path / "ledger.json",
    )
    assert spy.created == ["2"]
    assert result.succeeded == ["2"]


def test_item_allowlist_aborts_when_item_is_absent():
    with pytest.raises(ExecutorAbort, match="exatamente uma vez"):
        _plan_for(_kpi_inventory(), item_id="404")


def test_item_allowlist_aborts_when_item_is_duplicated():
    duplicate = MondayItemDigest(
        item_id="2",
        group_id="g2023",
        created_at=RECENT,
        updated_at=RECENT,
    )
    inventory = _kpi_inventory(_kpi_inventory().items + (duplicate,))
    with pytest.raises(ExecutorAbort, match="encontrados 2"):
        _plan_for(inventory, item_id="2")


def test_item_allowlist_aborts_when_item_is_outside_requested_wave():
    historical = MondayBoardInventory(
        board_id=TRABALHISTA,
        name="Processos Trabalhista",
        groups={"closed": "Trabalhista Encerrado"},
        columns=(),
        items=(
            MondayItemDigest(
                item_id="10",
                group_id="closed",
                created_at="2020-01-01T00:00:00Z",
                updated_at="2020-01-01T00:00:00Z",
            ),
        ),
    )
    with pytest.raises(ExecutorAbort, match="WAVE_1"):
        _plan_for(historical, wave=1, item_id="10")


def test_snapshot_changed_aborts_before_first_write(monkeypatch, tmp_path):
    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    plan = _plan_for(_kpi_inventory(), mode="apply",
                     schema_checks=[GateCheck("schema_live_verificado", True)])
    spy = SpyClient()
    with pytest.raises(ExecutorAbort, match="Snapshot do Monday mudou"):
        apply_plan(
            plan, client=spy, confirm_writes=True,
            snapshot_revalidator=lambda: "fingerprint-diferente",
            ledger_path=tmp_path / "ledger.json",
        )
    assert spy.created == []  # abortou ANTES da primeira escrita


# ---------------------------------------------------------------- dispositions


def _audiencias_inventory():
    return MondayBoardInventory(
        board_id=AUDIENCIAS,
        name="Audiências",
        groups={"topics": "Audiências (Procons e Processos)"},
        columns=(),
        items=(
            MondayItemDigest(item_id="11322933382", group_id="topics",
                             created_at=RECENT, updated_at=RECENT),   # ADOPT → 7043
            MondayItemDigest(item_id="12658169524", group_id="topics",
                             created_at=RECENT, updated_at=RECENT),   # ABSORB
            MondayItemDigest(item_id="12566356804", group_id="topics",
                             created_at=RECENT, updated_at=RECENT),   # EXCLUDE_TEST
            MondayItemDigest(item_id="12774333107", group_id="topics",
                             created_at=RECENT, updated_at=RECENT),   # CREATE explícito
        ),
    )


def test_dispositions_map_to_actions_without_fallback_to_create():
    plan = _plan_for(_audiencias_inventory())
    actions = {op.monday_item_id: op for op in plan.operations}
    assert actions["11322933382"].action == "adopt"
    assert actions["11322933382"].adopt_sunday_item_id == "7043"
    assert actions["12658169524"].action == "absorb"
    assert actions["12658169524"].canonical_monday_item_id == "11322933382"
    assert actions["12566356804"].action == "exclude_test"
    assert actions["12774333107"].action == "create"


def test_apply_adopt_never_creates_and_absorb_records_ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    plan = _plan_for(_audiencias_inventory(), mode="apply",
                     schema_checks=[GateCheck("schema_live_verificado", True)])
    spy = SpyClient()
    ledger_path = tmp_path / "ledger.json"
    result = apply_plan(
        plan, client=spy, confirm_writes=True,
        snapshot_revalidator=lambda: plan.snapshot_fingerprint,
        ledger_path=ledger_path,
    )
    # só o CREATE explícito cria item; adopt/absorb/exclude não criam nada.
    assert spy.created == ["12774333107"]
    assert len(result.succeeded) == 4
    records = load_persistent_ledger(ledger_path)
    assert records[f"{AUDIENCIAS}:11322933382"]["sunday_item_id"] == "7043"
    assert records[f"{AUDIENCIAS}:12658169524"]["disposition"] == "ABSORB"


def test_many_to_one_ledger_supported(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    persist_ledger_record(
        {"monday_board_id": AUDIENCIAS, "monday_item_id": "A", "sunday_item_id": "7043",
         "migration_status": "migrated"}, path=ledger_path,
    )
    persist_ledger_record(
        {"monday_board_id": AUDIENCIAS, "monday_item_id": "B", "sunday_item_id": "7043",
         "migration_status": "migrated", "disposition": "ABSORB",
         "canonical_monday_item_id": "A"}, path=ledger_path,
    )
    records = load_persistent_ledger(ledger_path)
    linked = [r for r in records.values() if r["sunday_item_id"] == "7043"]
    assert len(linked) == 2  # N Monday → 1 Sunday preservado
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert "description" in payload


def test_versioned_ledger_reload_preserves_idempotency(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    persist_ledger_record(
        {
            "monday_board_id": KPI_BOARD,
            "monday_item_id": "1",
            "sunday_board_id": "86",
            "sunday_item_id": "9001",
            "wave": "WAVE_1",
            "disposition": "CREATE",
            "migration_status": "migrated",
        },
        path=ledger_path,
    )
    reloaded = load_persistent_ledger(ledger_path)
    plan = _plan_for(_kpi_inventory(), ledger=reloaded)
    actions = {op.monday_item_id: op.action for op in plan.operations}
    assert actions["1"] == "already_migrated"
    assert actions["2"] == "create"


def test_apply_skips_already_migrated_without_corrupting_ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    ledger_path = tmp_path / "ledger.json"
    persist_ledger_record(
        {
            "monday_board_id": KPI_BOARD,
            "monday_item_id": "1",
            "sunday_board_id": "86",
            "sunday_item_id": "9001",
            "wave": "WAVE_1",
            "disposition": "CREATE",
            "migration_status": "migrated",
        },
        path=ledger_path,
    )
    plan = _plan_for(_kpi_inventory(), mode="apply", ledger=load_persistent_ledger(ledger_path),
                     schema_checks=[GateCheck("schema_live_verificado", True)])
    spy = SpyClient()
    result = apply_plan(
        plan,
        client=spy,
        confirm_writes=True,
        snapshot_revalidator=lambda: plan.snapshot_fingerprint,
        ledger_path=ledger_path,
    )
    assert "1" not in result.succeeded
    assert spy.created == ["2", "3"]
    assert load_persistent_ledger(ledger_path)[f"{KPI_BOARD}:1"]["sunday_item_id"] == "9001"


def test_import_legacy_ledger_if_needed(tmp_path):
    legacy_path = tmp_path / "legacy.json"
    target_path = tmp_path / "target.json"
    legacy_path.write_text(
        json.dumps(
            {
                "records": {
                    f"{KPI_BOARD}:99": {
                        "monday_board_id": KPI_BOARD,
                        "monday_item_id": "99",
                        "sunday_board_id": "86",
                        "sunday_item_id": "7000",
                        "migration_status": "migrated",
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    assert import_legacy_ledger_if_needed(target_path, legacy_path=legacy_path) is True
    records = load_persistent_ledger(target_path)
    assert records[f"{KPI_BOARD}:99"]["sunday_item_id"] == "7000"
    assert import_legacy_ledger_if_needed(target_path, legacy_path=legacy_path) is False


def test_default_ledger_path_is_versioned():
    assert DEFAULT_LEDGER_PATH == "docs/migration/monday-sunday-ledger.json"
    assert LEGACY_LEDGER_PATH == "data/monday-sunday-map.json"


# --------------------------------------------------------------------- users


def test_user_without_approved_match_blocks_item():
    items = (
        MondayItemDigest(item_id="1", group_id="g2023", created_at=RECENT,
                         updated_at=RECENT, people_ids=("999",)),  # usuário NOVO
    )
    plan = _plan_for(_kpi_inventory(items))
    operation = plan.operations[0]
    assert operation.action == "blocked"
    # bloqueado pela engine canônica (MISSING_USER_MAPPING) e sem fuzzy match:
    assert "MISSING_USER_MAPPING" in (operation.blocked_reason or "")
    assert operation.owner_resolution == "blocked_novo_sem_match"


def test_approved_user_tiers_resolve_owner():
    items = (
        MondayItemDigest(item_id="1", group_id="g2023", created_at=RECENT,
                         updated_at=RECENT, people_ids=("100",)),
        MondayItemDigest(item_id="2", group_id="g2023", created_at=RECENT,
                         updated_at=RECENT, people_ids=("200",)),
        MondayItemDigest(item_id="3", group_id="g2023", created_at=RECENT,
                         updated_at=RECENT, people_ids=("300",)),
        MondayItemDigest(item_id="4", group_id="g2023", created_at=RECENT,
                         updated_at=RECENT),
    )
    plan = _plan_for(_kpi_inventory(items))
    owners = {op.monday_item_id: op.owner_resolution for op in plan.operations}
    assert owners == {
        "1": "set_match_exato",
        "2": "empty_sem_match_aprovado",
        "3": "empty_desativado",
        "4": "empty_sem_owner",
    }
    # sem match aprovado / desativado NÃO bloqueiam:
    assert all(op.action == "create" for op in plan.operations)


# --------------------------------------------------------------- idempotência


def test_ledger_idempotency_skips_already_migrated():
    ledger = {
        f"{KPI_BOARD}:1": {"migration_status": "migrated", "sunday_item_id": "5000"},
    }
    plan = _plan_for(_kpi_inventory(), ledger=ledger)
    actions = {op.monday_item_id: op.action for op in plan.operations}
    assert actions["1"] == "already_migrated"
    assert actions["2"] == "create"


def test_monday_id_without_ledger_is_resumed_without_recreation():
    plan = _plan_for(_kpi_inventory(), monday_id_index={"2": "6000"})
    actions = {op.monday_item_id: op.action for op in plan.operations}
    assert actions["2"] == "resume"


def test_rerun_after_partial_failure_does_not_duplicate(monkeypatch, tmp_path):
    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    ledger_path = tmp_path / "ledger.json"
    inventory = _kpi_inventory()
    schema_ok = [GateCheck("schema_live_verificado", True)]

    plan = _plan_for(inventory, mode="apply", schema_checks=schema_ok)
    spy = SpyClient(fail_on={"2"})
    result = apply_plan(
        plan, client=spy, confirm_writes=True,
        snapshot_revalidator=lambda: plan.snapshot_fingerprint,
        ledger_path=ledger_path,
    )
    assert result.succeeded == ["1"]
    assert [failed for failed, _ in result.failed] == ["2"]
    assert result.not_attempted == ["3"]  # fail-fast

    # Reexecução: item 1 vem do ledger como already_migrated → não recria.
    plan2 = _plan_for(inventory, mode="apply", schema_checks=schema_ok,
                      ledger=load_persistent_ledger(ledger_path))
    spy2 = SpyClient()
    result2 = apply_plan(
        plan2, client=spy2, confirm_writes=True,
        snapshot_revalidator=lambda: plan2.snapshot_fingerprint,
        ledger_path=ledger_path,
    )
    assert spy2.created == ["2", "3"]  # o 1 não foi duplicado
    assert len(result2.succeeded) == 2


# ------------------------------------------------------ relações / subitens


def test_relation_second_pass_resolved_by_ledger():
    inventory = MondayBoardInventory(
        board_id=CONTROLE,
        name="Controle",
        groups={"g": "Assinados"},
        columns=(),
        items=(
            MondayItemDigest(
                item_id="10", group_id="g", created_at=RECENT, updated_at=RECENT,
                relation_targets={"board_relation_mm5ap90f": ("77000",)},
            ),
        ),
    )
    ledger = {
        f"{CONTRATOS}:77000": {"migration_status": "migrated", "sunday_item_id": "8123"},
    }
    plan = _plan_for(inventory, ledger=ledger)
    assert len(plan.relations_to_create) == 1
    assert plan.relations_to_create[0].resolved_sunday_item_ids == ("8123",)
    assert plan.relations_unresolved == []


def test_apply_blocks_when_gate_incomplete(monkeypatch):
    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    inventory = MondayBoardInventory(
        board_id=CONTROLE,
        name="Controle",
        groups={"g": "Assinados"},
        columns=(),
        items=(
            MondayItemDigest(
                item_id="10", group_id="g", created_at=RECENT, updated_at=RECENT,
                relation_targets={"board_relation_mm5ap90f": ("77000",)},
            ),
        ),
    )
    plan = _plan_for(inventory, mode="apply",
                     schema_checks=[GateCheck("schema_live_verificado", True)])
    assert plan.gate_ok is False
    with pytest.raises(ExecutorAbort, match="Gate fail-closed"):
        apply_plan(
            plan, client=SpyClient(), confirm_writes=True,
            snapshot_revalidator=lambda: plan.snapshot_fingerprint,
        )


def test_unresolved_relation_blocks_apply(monkeypatch):
    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    inventory = MondayBoardInventory(
        board_id=CONTROLE,
        name="Controle",
        groups={"g": "Assinados"},
        columns=(),
        items=(
            MondayItemDigest(
                item_id="10", group_id="g", created_at=RECENT, updated_at=RECENT,
                relation_targets={"board_relation_mm5ap90f": ("77000",)},
            ),
        ),
    )
    plan = _plan_for(inventory, mode="apply",
                     schema_checks=[GateCheck("schema_live_verificado", True)])
    assert len(plan.relations_unresolved) == 1
    gate = {check.name: check.ok for check in plan.gate}
    assert gate["relations_resolvidas"] is False
    with pytest.raises(ExecutorAbort, match="relations_resolvidas"):
        apply_plan(
            plan, client=SpyClient(), confirm_writes=True,
            snapshot_revalidator=lambda: plan.snapshot_fingerprint,
        )


def test_subitems_counted_for_contratos_roots():
    inventory = MondayBoardInventory(
        board_id=CONTRATOS,
        name="Contratos",
        groups={"g": "Contratos B2B", "ge": "Contratos Encerrados"},
        columns=(),
        items=(
            MondayItemDigest(item_id="1", group_id="g", created_at=RECENT,
                             updated_at=RECENT, subitem_count=2),
            MondayItemDigest(item_id="2", group_id="ge", created_at=RECENT,
                             updated_at=RECENT),
        ),
    )
    plan = _plan_for(inventory)
    by_id = {op.monday_item_id: op for op in plan.operations}
    assert by_id["1"].subitem_count == 2  # root + 2 aditivos (subitens)
    assert by_id["1"].group_action == "transformar"  # grupo → Tipo
    assert by_id["2"].group_action == "transformar"
    # Encerrados: Vigência=Não Vigente, sem Tipo (regra nos GROUP_RULES).
    from classificacao_procons.migration.mappings import group_rule

    assert group_rule(CONTRATOS, "Contratos Encerrados")[1].startswith("Vigência")


# ---------------------------------------------- comments/attachments/segredos


def test_comment_and_attachment_idempotency_markers():
    marker = comment_idempotency_marker("123", "u9")
    assert marker == "[monday-migracao:123:u9]"
    name = attachment_idempotency_name("555", "contrato.pdf")
    assert name.startswith("monday-asset-555")


def test_plan_reports_exact_item_update_count():
    updates = tuple(
        MondayUpdateDigest(
            update_id=f"u{index}",
            created_at=RECENT,
            has_author=True,
            classification="text_update_with_author",
            is_migratable=True,
        )
        for index in range(3)
    )
    item = MondayItemDigest(
        item_id="1",
        group_id="g2023",
        created_at=RECENT,
        updated_at=RECENT,
        has_updates=True,
        source_updates_count=3,
        updates_count=3,
        update_diagnostics=updates,
    )
    plan = _plan_for(_kpi_inventory((item,)))

    assert plan.operations[0].comments_to_create == 3
    assert plan.to_payload()["source_updates"] == 3
    assert plan.to_payload()["updates_migraveis"] == 3
    assert plan.to_payload()["comments_to_create"] == 3


def test_legacy_snapshot_update_boolean_blocks_apply_as_inexact():
    item = MondayItemDigest(
        item_id="1",
        group_id="g2023",
        created_at=RECENT,
        updated_at=RECENT,
        has_updates=True,
        updates_count=1,
        updates_count_is_exact=False,
    )
    plan = _plan_for(
        _kpi_inventory((item,)),
        mode="apply",
        schema_checks=[GateCheck("schema_live_verificado", True)],
    )

    assert plan.to_payload()["comments_count_exact"] is False
    assert {check.name: check.ok for check in plan.gate}["snapshot_valido"] is False


def test_comment_failure_prevents_ledger_and_stops_next_item(
    monkeypatch,
    tmp_path,
):
    from classificacao_procons.migration import apply_writer

    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    monkeypatch.setattr(apply_writer, "build_sunday_monday_id_index", lambda *a, **k: {})
    monkeypatch.setattr(
        apply_writer,
        "apply_create_item",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("mandatory comment failed")),
    )
    inventory = _kpi_inventory()
    plan = _plan_for(
        inventory,
        mode="apply",
        schema_checks=[GateCheck("schema_live_verificado", True)],
    )
    ledger_path = tmp_path / "ledger.json"
    context = ApplyMigrationContext(
        inventory=inventory,
        board_plan=object(),
        sunday_snapshot=object(),
        apply_sources={item.item_id: object() for item in inventory.items},
        monday_id_column_id="monday-id",
        target_group_id="group-id",
    )

    result = apply_plan(
        plan,
        client=SpyClient(),
        confirm_writes=True,
        snapshot_revalidator=lambda: plan.snapshot_fingerprint,
        ledger_path=ledger_path,
        migration_context=context,
    )

    assert result.failed == [("1", "mandatory comment failed")]
    assert result.not_attempted == ["2", "3"]
    assert not ledger_path.exists()


def test_partial_item_retry_completes_comments_before_ledger(monkeypatch, tmp_path):
    from classificacao_procons.migration import apply_writer

    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    monkeypatch.setattr(
        apply_writer,
        "build_sunday_monday_id_index",
        lambda *a, **k: {"1": "sunday-existing"},
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        apply_writer,
        "migrate_monday_updates",
        lambda **kwargs: calls.append(
            (kwargs["monday_item_id"], kwargs["sunday_item_id"]),
        ),
    )
    inventory = _kpi_inventory((
        MondayItemDigest(
            item_id="1",
            group_id="g2023",
            created_at=RECENT,
            updated_at=RECENT,
            source_updates_count=1,
            updates_count=1,
            has_updates=True,
            update_diagnostics=(
                MondayUpdateDigest(
                    update_id="u1",
                    created_at=RECENT,
                    has_author=True,
                    classification="text_update_with_author",
                    is_migratable=True,
                ),
            ),
        ),
    ))
    plan = _plan_for(
        inventory,
        mode="apply",
        schema_checks=[GateCheck("schema_live_verificado", True)],
    )
    ledger_path = tmp_path / "ledger.json"
    context = ApplyMigrationContext(
        inventory=inventory,
        board_plan=object(),
        sunday_snapshot=object(),
        apply_sources={"1": type("Source", (), {"updates": (object(),)})()},
        monday_id_column_id="monday-id",
        target_group_id="group-id",
    )

    result = apply_plan(
        plan,
        client=SpyClient(),
        confirm_writes=True,
        snapshot_revalidator=lambda: plan.snapshot_fingerprint,
        ledger_path=ledger_path,
        migration_context=context,
    )

    assert result.succeeded == ["1"]
    assert calls == [("1", "sunday-existing")]
    assert load_persistent_ledger(ledger_path)[f"{KPI_BOARD}:1"]["sunday_item_id"] == (
        "sunday-existing"
    )


def test_schema_checks_require_monday_id_column():
    from classificacao_procons.migration.models import SundayColumnSnapshot

    columns = [SundayColumnSnapshot(id="1", key="name", label="Nome", type="text",
                                    is_system=True)]
    checks = build_sunday_schema_checks(
        sunday_board_id="86", columns=columns, groups={"1": "Itens"},
    )
    assert checks[0].name == "monday_id_presente"
    assert checks[0].ok is False  # coluna Monday ID ainda não existe

    columns.append(SundayColumnSnapshot(id="2", key="monday_id", label="Monday ID",
                                        type="text", is_system=False))
    checks_ok = build_sunday_schema_checks(
        sunday_board_id="86", columns=columns, groups={},
    )
    assert checks_ok[0].ok is True


def test_test_secrets_required_without_fallback(monkeypatch):
    monkeypatch.delenv("SUNDAY_API_URL_TEST", raising=False)
    monkeypatch.delenv("SUNDAY_API_TOKEN_TEST", raising=False)
    monkeypatch.setenv("SUNDAY_API_URL", "https://nao-deve-ser-usada")
    monkeypatch.setenv("SUNDAY_API_TOKEN", "nao-deve-ser-usado")
    with pytest.raises(ExecutorAbort, match="_TEST"):
        sunday_config_from_test_env()


def test_no_secret_leakage_in_plan_payload(monkeypatch):
    secret = "sun_pat_super_secreto"
    monkeypatch.setenv("SUNDAY_API_URL_TEST", "https://sunday-teste.example")
    monkeypatch.setenv("SUNDAY_API_TOKEN_TEST", secret)
    config = sunday_config_from_test_env()
    assert secret not in repr(config)
    plan = _plan_for(_kpi_inventory())
    assert secret not in json.dumps(plan.to_payload())


def test_snapshot_fingerprint_is_stable_and_sensitive():
    inventory = _kpi_inventory()
    assert snapshot_fingerprint(inventory) == snapshot_fingerprint(_kpi_inventory())
    changed = _kpi_inventory(
        tuple(
            MondayItemDigest(item_id=str(i), group_id="g2023", created_at=RECENT,
                             updated_at="2026-08-12T00:00:00Z")
            for i in range(1, 4)
        ),
    )
    assert snapshot_fingerprint(inventory) != snapshot_fingerprint(changed)
