"""Testes do ledger durável e sync plan read-only."""

from __future__ import annotations

from classificacao_procons.migration.executor import (
    ApplyReport,
    LedgerWriteReport,
    apply_plan,
    load_persistent_ledger,
    persist_ledger_record,
)
from classificacao_procons.migration.ledger_sync import (
    LiveProvenMapping,
    build_ledger_sync_plan,
    verify_ledger_record_persisted,
)
from classificacao_procons.migration.source_audit import classify_missing_comment_marker

KPI_BOARD = "5563754463"


def test_verify_ledger_record_persisted_requires_read_back(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    record = {
        "monday_board_id": KPI_BOARD,
        "monday_item_id": "1",
        "sunday_board_id": "86",
        "sunday_item_id": "9001",
        "migration_status": "migrated",
    }
    assert verify_ledger_record_persisted(record, ledger_path=ledger_path) is False
    persist_ledger_record(record, path=ledger_path)
    assert verify_ledger_record_persisted(record, ledger_path=ledger_path) is True


def test_build_ledger_sync_plan_adds_only_missing_proven_mappings(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    persist_ledger_record(
        {
            "monday_board_id": "4944254220",
            "monday_item_id": "10021122897",
            "sunday_board_id": "82",
            "sunday_item_id": "7805",
            "migration_status": "migrated",
        },
        path=ledger_path,
    )
    live_mappings = [
        LiveProvenMapping(
            monday_board_id="4944254220",
            monday_item_id="10021122897",
            sunday_board_id="82",
            sunday_item_id="7805",
            monday_id_column_raw="4944254220/10021122897",
        ),
        LiveProvenMapping(
            monday_board_id="4944254220",
            monday_item_id="10804000207",
            sunday_board_id="82",
            sunday_item_id="7803",
            monday_id_column_raw="4944254220/10804000207",
        ),
    ]
    plan = build_ledger_sync_plan(
        live_mappings=live_mappings,
        ledger_path=ledger_path,
    )
    assert plan.records_canonical_before == 1
    assert plan.live_proven_mappings == 2
    assert len(plan.records_to_add) == 1
    assert plan.records_to_add[0].monday_item_id == "10804000207"
    assert plan.records_to_modify == []
    assert plan.records_to_delete == []
    assert plan.canonical_conflicts == 0


def test_ledger_sync_plan_is_idempotent_after_sync(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    mapping = LiveProvenMapping(
        monday_board_id="4944254220",
        monday_item_id="10804000207",
        sunday_board_id="82",
        sunday_item_id="7803",
        monday_id_column_raw="4944254220/10804000207",
    )
    first = build_ledger_sync_plan(live_mappings=[mapping], ledger_path=ledger_path)
    assert len(first.records_to_add) == 1
    persist_ledger_record(
        {
            "monday_board_id": mapping.monday_board_id,
            "monday_item_id": mapping.monday_item_id,
            "sunday_board_id": mapping.sunday_board_id,
            "sunday_item_id": mapping.sunday_item_id,
            "migration_status": "migrated",
        },
        path=ledger_path,
    )
    second = build_ledger_sync_plan(live_mappings=[mapping], ledger_path=ledger_path)
    assert second.idempotent is True
    assert second.records_to_add == []


def test_apply_plan_reports_durable_ledger_confirmed(monkeypatch, tmp_path):
    from classificacao_procons.migration.dry_run import run_dry_run
    from classificacao_procons.migration.executor import (
        GateCheck,
        build_execution_plan,
    )
    from classificacao_procons.migration.models import (
        MondayBoardInventory,
        MondayColumnInfo,
        MondayItemDigest,
    )
    from classificacao_procons.migration.user_mapping import UserMappingPolicy

    class SpyClient:
        def __init__(self):
            self.created: list[str] = []
            self._next_id = 9000

        def create_item(self, board_id, name, **kwargs):
            self._next_id += 1
            marker = name.split()[-1]
            self.created.append(marker)
            return type("Created", (), {"id": str(self._next_id)})()

    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    ledger_path = tmp_path / "ledger.json"
    inventory = MondayBoardInventory(
        board_id=KPI_BOARD,
        name="KPI",
        groups={"g2023": "2023"},
        columns=(MondayColumnInfo(id="name", title="Name", type="name"),),
        items=tuple(
            MondayItemDigest(
                item_id=str(i),
                group_id="g2023",
                created_at="2026-08-01T00:00:00Z",
                updated_at="2026-08-01T00:00:00Z",
            )
            for i in range(1, 4)
        ),
    )
    policy = UserMappingPolicy(
        exact_match_ids=frozenset(),
        active_unmatched_ids=frozenset(),
        deactivated_ids=frozenset(),
    )
    report, _plans, _pulled = run_dry_run({inventory.board_id: inventory}, {}, user_policy=policy)
    plan = build_execution_plan(
        inventory=inventory,
        report=report,
        wave=1,
        max_items=50,
        mode="apply",
        user_policy=policy,
        sunday_schema_checks=[GateCheck("schema_live_verificado", True)],
    )
    result = apply_plan(
        plan,
        client=SpyClient(),
        confirm_writes=True,
        snapshot_revalidator=lambda: plan.snapshot_fingerprint,
        ledger_path=ledger_path,
    )
    assert result.ledger.expected == 3
    assert result.ledger.durable_confirmed == 3
    assert result.ledger.failed == 0
    assert len(load_persistent_ledger(ledger_path)) == 3


def test_post_migration_comment_delta_is_not_migration_miss():
    assert classify_missing_comment_marker(
        update_created_at="2026-08-12T22:12:09.000Z",
        migrated_at="2026-08-12T18:09:52.444065+00:00",
        source_snapshot_timestamp="2026-08-12T18:09:12.542587+00:00",
    ) == "POST_MIGRATION_DELTA"


def test_migration_miss_when_update_existed_at_snapshot():
    assert classify_missing_comment_marker(
        update_created_at="2026-08-12T18:08:00.000Z",
        migrated_at="2026-08-12T18:09:52.444065+00:00",
        source_snapshot_timestamp="2026-08-12T18:09:12.542587+00:00",
    ) == "MIGRATION_MISS"


def test_ledger_write_report_serializes_explicit_semantics():
    report = LedgerWriteReport(
        expected=10,
        durable_confirmed=10,
        pending_sync=0,
        failed=0,
    )
    payload = ApplyReport(ledger=report).ledger.as_dict()
    assert payload["ledger_expected"] == 10
    assert payload["ledger_durable_confirmed"] == 10
    assert payload["ledger_pending_sync"] == 0
    assert payload["ledger_failed"] == 0
