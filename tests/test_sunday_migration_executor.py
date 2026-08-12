"""Testes do executor Fase 3 — PLAN nunca escreve; APPLY fail-closed (mockado)."""

from __future__ import annotations

import json

import pytest

from classificacao_procons.migration.dry_run import run_dry_run
from classificacao_procons.migration.executor import (
    BOARD_ALLOWLIST,
    DEFAULT_LEDGER_PATH,
    LEGACY_LEDGER_PATH,
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
)
from classificacao_procons.migration.user_mapping import UserMappingPolicy

RECENT = "2026-08-01T00:00:00Z"
KPI_BOARD = "5563754463"
CONTROLE = "5301515799"
CONTRATOS = "5385471914"
AUDIENCIAS = "4443295406"

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


def _plan_for(inventory, *, wave=1, max_items=50, mode="plan", ledger=None,
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


def test_monday_id_idempotency_skips_existing_sunday_item():
    plan = _plan_for(_kpi_inventory(), monday_id_index={"2": "6000"})
    actions = {op.monday_item_id: op.action for op in plan.operations}
    assert actions["2"] == "already_migrated"


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
    assert len(result2.succeeded) == 3


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


# ------------------------------------------------------- item allowlist (1 item)


def _plan_kwargs(inventory, **overrides):
    report, _plans, _pulled = run_dry_run(
        {inventory.board_id: inventory},
        {},
        user_policy=POLICY,
        users_mapped=set(POLICY.exact_match_ids),
    )
    kwargs = dict(
        inventory=inventory,
        report=report,
        wave=1,
        max_items=50,
        mode="plan",
        user_policy=POLICY,
    )
    kwargs.update(overrides)
    return kwargs


def test_item_allowlist_restricts_plan_to_explicit_item():
    plan = build_execution_plan(**_plan_kwargs(_kpi_inventory(), item_allowlist=("2",)))
    assert [op.monday_item_id for op in plan.operations] == ["2"]
    assert plan.item_allowlist == ("2",)
    payload = plan.to_payload()
    assert payload["item_allowlist"] == ["2"]
    assert payload["counts"] == {"create": 1}


def test_item_allowlist_unknown_item_aborts():
    with pytest.raises(ExecutorAbort, match="não encontrado"):
        build_execution_plan(**_plan_kwargs(_kpi_inventory(), item_allowlist=("999",)))


def test_item_allowlist_item_outside_wave_aborts():
    # itens do KPI são WAVE_1; pedir WAVE_2 não encontra o item → abort.
    with pytest.raises(ExecutorAbort, match="não encontrado"):
        build_execution_plan(
            **_plan_kwargs(_kpi_inventory(), wave=2, item_allowlist=("2",)),
        )


def test_item_allowlist_duplicate_or_empty_ids_abort():
    with pytest.raises(ExecutorAbort, match="duplicado"):
        build_execution_plan(
            **_plan_kwargs(_kpi_inventory(), item_allowlist=("2", "2")),
        )
    with pytest.raises(ExecutorAbort, match="vazia"):
        build_execution_plan(**_plan_kwargs(_kpi_inventory(), item_allowlist=()))
    with pytest.raises(ExecutorAbort, match="vazio"):
        build_execution_plan(**_plan_kwargs(_kpi_inventory(), item_allowlist=(" ",)))


def test_item_allowlist_ambiguous_match_aborts():
    duplicated = _kpi_inventory()
    report, _plans, _pulled = run_dry_run(
        {duplicated.board_id: duplicated},
        {},
        user_policy=POLICY,
        users_mapped=set(POLICY.exact_match_ids),
    )
    report.items.append(report.items[1])  # simula source row duplicada para o id 2
    with pytest.raises(ExecutorAbort, match="ambíguo"):
        build_execution_plan(
            inventory=duplicated,
            report=report,
            wave=1,
            max_items=50,
            user_policy=POLICY,
            item_allowlist=("2",),
        )


def test_apply_with_item_allowlist_writes_only_that_item(monkeypatch, tmp_path):
    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    plan = build_execution_plan(
        **_plan_kwargs(
            _kpi_inventory(),
            mode="apply",
            item_allowlist=("2",),
            sunday_schema_checks=[GateCheck("schema_live_verificado", True)],
        ),
    )
    spy = SpyClient()
    ledger_path = tmp_path / "ledger.json"
    result = apply_plan(
        plan, client=spy, confirm_writes=True,
        snapshot_revalidator=lambda: plan.snapshot_fingerprint,
        ledger_path=ledger_path,
    )
    assert spy.created == ["2"]  # SOMENTE o item da allowlist
    assert result.succeeded == ["2"]
    records = load_persistent_ledger(ledger_path)
    assert set(records) == {f"{KPI_BOARD}:2"}


def test_apply_max_items_still_enforced_with_item_allowlist(monkeypatch):
    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    plan = build_execution_plan(
        **_plan_kwargs(
            _kpi_inventory(),
            mode="apply",
            max_items=0,
            item_allowlist=("2",),
            sunday_schema_checks=[GateCheck("schema_live_verificado", True)],
        ),
    )
    gate = {check.name: check.ok for check in plan.gate}
    assert gate["max_items"] is False
    with pytest.raises(ExecutorAbort, match="max_items"):
        apply_plan(
            plan, client=SpyClient(), confirm_writes=True,
            snapshot_revalidator=lambda: plan.snapshot_fingerprint,
        )


def test_apply_aborts_when_scope_differs_from_allowlist(monkeypatch, tmp_path):
    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    plan = build_execution_plan(
        **_plan_kwargs(
            _kpi_inventory(),
            mode="apply",
            item_allowlist=("2",),
            sunday_schema_checks=[GateCheck("schema_live_verificado", True)],
        ),
    )
    full_plan = build_execution_plan(
        **_plan_kwargs(
            _kpi_inventory(),
            mode="apply",
            sunday_schema_checks=[GateCheck("schema_live_verificado", True)],
        ),
    )
    plan.operations = full_plan.operations  # plano adulterado (escopo ≠ allowlist)
    spy = SpyClient()
    with pytest.raises(ExecutorAbort, match="allowlist"):
        apply_plan(
            plan, client=spy, confirm_writes=True,
            snapshot_revalidator=lambda: plan.snapshot_fingerprint,
            ledger_path=tmp_path / "ledger.json",
        )
    assert spy.created == []  # abortou antes da primeira escrita


# ---------------------------------------------- comments/attachments/segredos


def test_comment_and_attachment_idempotency_markers():
    marker = comment_idempotency_marker("123", "u9")
    assert marker == "[monday-migracao:123:u9]"
    name = attachment_idempotency_name("555", "contrato.pdf")
    assert name.startswith("monday-asset-555")


class CommentSpyClient:
    """Client espião só de comments (list + add)."""

    def __init__(self, existing_bodies: list[str] | None = None):
        self._existing = list(existing_bodies or [])
        self.added: list[str] = []

    def list_comments(self, item_id):
        from types import SimpleNamespace

        return [SimpleNamespace(body=body) for body in self._existing]

    def add_comment(self, item_id, body, **kwargs):
        self.added.append(body)
        self._existing.append(body)


def test_comment_body_preserves_author_date_and_marker():
    from classificacao_procons.migration.apply_writer import (
        MondayUpdateSource,
        build_migration_comment_body,
    )

    update = MondayUpdateSource(
        update_id="u1", body="andamento do processo",
        creator_name="Fulano", created_at="2026-08-01T10:00:00Z",
    )
    body = build_migration_comment_body("123", update)
    assert body.startswith("[Monday · Fulano · 2026-08-01T10:00:00Z]")
    assert "andamento do processo" in body
    assert body.rstrip().endswith("[monday-migracao:123:u1]")


def test_apply_create_comments_is_idempotent_by_marker():
    from classificacao_procons.migration.apply_writer import (
        ApplyWriteStats,
        MondayUpdateSource,
        apply_create_comments,
    )

    updates = (
        MondayUpdateSource(update_id="u1", body="primeiro"),
        MondayUpdateSource(update_id="u2", body="segundo"),
    )
    spy = CommentSpyClient()
    stats = ApplyWriteStats()
    created = apply_create_comments(
        client=spy, sunday_item_id="9001", monday_item_id="123",
        updates=updates, stats=stats,
    )
    assert created == 2
    assert stats.comments == 2
    assert "[monday-migracao:123:u1]" in spy.added[0]
    assert "[monday-migracao:123:u2]" in spy.added[1]

    # Reexecução: os marcadores já existem → NENHUM comment duplicado.
    rerun = apply_create_comments(
        client=spy, sunday_item_id="9001", monday_item_id="123",
        updates=updates, stats=stats,
    )
    assert rerun == 0
    assert len(spy.added) == 2
    assert stats.comments == 2


def test_fetch_monday_item_updates_sorts_oldest_first(monkeypatch):
    from classificacao_procons.migration import apply_writer

    def fake_graphql(**kwargs):
        return {
            "items": [
                {
                    "id": "123",
                    "updates": [
                        {"id": "u2", "text_body": "novo",
                         "created_at": "2026-08-02T00:00:00Z",
                         "creator": {"name": "B"}},
                        {"id": "u1", "text_body": "antigo",
                         "created_at": "2026-08-01T00:00:00Z",
                         "creator": {"name": "A"}},
                    ],
                },
            ],
        }

    monkeypatch.setattr(apply_writer, "_graphql_request", fake_graphql)
    result = apply_writer.fetch_monday_item_updates("token", ["123"])
    assert [update.update_id for update in result["123"]] == ["u1", "u2"]
    assert result["123"][0].creator_name == "A"


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
