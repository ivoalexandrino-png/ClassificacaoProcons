"""Testes do ledger durável, sync plan e estados versionados."""

from __future__ import annotations

import subprocess

from classificacao_procons.migration.executor import (
    ApplyReport,
    ExecutorAbort,
    LedgerWriteReport,
    apply_plan,
    persist_ledger_record,
)
from classificacao_procons.migration.ledger_sync import (
    LiveProvenMapping,
    apply_ledger_sync_plan,
    assess_ledger_state,
    build_ledger_sync_plan,
    classify_ledger_write_outcome,
    load_versioned_ledger_from_git,
    validate_apply_ledger_gate,
    verify_ledger_record_persisted,
)
from classificacao_procons.migration.source_audit import classify_missing_comment_marker

KPI_BOARD = "5563754463"
PROCONS_BOARD = "4944254220"


def _mapping(
    monday_item_id: str,
    sunday_item_id: str,
    *,
    board: str = PROCONS_BOARD,
    sunday_board: str = "82",
) -> LiveProvenMapping:
    return LiveProvenMapping(
        monday_board_id=board,
        monday_item_id=monday_item_id,
        sunday_board_id=sunday_board,
        sunday_item_id=sunday_item_id,
        monday_id_column_raw=f"{board}/{monday_item_id}",
    )


def _init_git_repo(tmp_path, ledger_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        '{"schema_version":1,"records":{}}',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", ledger_path.name], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init ledger"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


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


def test_sync_plan_before_sync_requires_changes():
    mapping = _mapping("10804000207", "7803")
    plan = build_ledger_sync_plan(
        canonical_ledger={},
        live_mappings=[mapping],
        ledger_path="ignored.json",
    )
    assert plan.changes_required is True
    assert plan.sync_idempotent is False
    assert len(plan.records_to_add) == 1


def test_sync_plan_after_sync_is_idempotent(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    mapping = _mapping("10804000207", "7803")
    first = build_ledger_sync_plan(live_mappings=[mapping], ledger_path=ledger_path)
    assert first.changes_required is True
    apply_ledger_sync_plan(first, ledger_path=ledger_path)
    second = build_ledger_sync_plan(live_mappings=[mapping], ledger_path=ledger_path)
    assert second.sync_idempotent is True
    assert second.changes_required is False
    assert second.records_to_add == []


def test_live_62_canonical_52_plan_add_10():
    canonical = {
        f"{PROCONS_BOARD}:{mid}": {
            "monday_board_id": PROCONS_BOARD,
            "monday_item_id": mid,
            "sunday_board_id": "82",
            "sunday_item_id": sid,
            "migration_status": "migrated",
        }
        for mid, sid in [("10946636665", "7760")]
    }
    live = [_mapping("10946636665", "7760")]
    live.extend(_mapping(f"1000000000{i}", f"780{i}") for i in range(10))
    plan = build_ledger_sync_plan(
        canonical_ledger=canonical,
        live_mappings=live,
        ledger_path="ignored.json",
    )
    assert plan.records_canonical_before == 1
    assert plan.live_proven_mappings == 11
    assert len(plan.records_to_add) == 10


def test_file_updated_but_git_head_old_reports_pending_commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    ledger_path = repo / "ledger.json"
    _init_git_repo(repo, ledger_path)
    mapping = _mapping("10804000207", "7803")
    plan = build_ledger_sync_plan(live_mappings=[mapping], ledger_path=ledger_path)
    apply_ledger_sync_plan(plan, ledger_path=ledger_path)
    state = assess_ledger_state(
        live_mappings=[mapping],
        ledger_path=ledger_path,
        repo_root=repo,
    )
    assert state.pending_sync == 0
    assert state.pending_commit == 1
    assert state.versioned_confirmed == 0
    assert validate_apply_ledger_gate(state) == [
        "ledger_pending_commit=1 "
        "(arquivo local diverge de Git HEAD — commit/merge do ledger obrigatório)",
    ]


def test_git_head_updated_reports_versioned_confirmed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    ledger_path = repo / "ledger.json"
    _init_git_repo(repo, ledger_path)
    mapping = _mapping("10804000207", "7803")
    plan = build_ledger_sync_plan(live_mappings=[mapping], ledger_path=ledger_path)
    apply_ledger_sync_plan(plan, ledger_path=ledger_path)
    subprocess.run(["git", "add", ledger_path.name], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "sync ledger"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    state = assess_ledger_state(
        live_mappings=[mapping],
        ledger_path=ledger_path,
        repo_root=repo,
    )
    assert state.pending_sync == 0
    assert state.pending_commit == 0
    assert state.versioned_confirmed == 1
    assert validate_apply_ledger_gate(state) == []


def test_pending_sync_blocks_apply_gate():
    mapping = _mapping("10804000207", "7803")
    state = assess_ledger_state(
        live_mappings=[mapping],
        ledger_path="/nonexistent/ledger.json",
    )
    assert state.pending_sync == 1
    failures = validate_apply_ledger_gate(state)
    assert any("ledger_pending_sync=1" in failure for failure in failures)


def test_classify_ledger_write_outcome_pending_commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    ledger_path = repo / "ledger.json"
    _init_git_repo(repo, ledger_path)
    record = {
        "monday_board_id": PROCONS_BOARD,
        "monday_item_id": "10804000207",
        "sunday_board_id": "82",
        "sunday_item_id": "7803",
        "migration_status": "migrated",
    }
    persist_ledger_record(record, path=ledger_path)
    assert classify_ledger_write_outcome(record, ledger_path=ledger_path, repo_root=repo) == (
        "pending_commit"
    )


def test_apply_plan_reports_file_persisted_and_pending_commit(monkeypatch, tmp_path):
    from classificacao_procons.migration.dry_run import run_dry_run
    from classificacao_procons.migration.executor import GateCheck, build_execution_plan
    from classificacao_procons.migration.ledger_sync import LedgerStateReport
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
    clean_gate = LedgerStateReport()
    result = apply_plan(
        plan,
        client=SpyClient(),
        confirm_writes=True,
        snapshot_revalidator=lambda: plan.snapshot_fingerprint,
        ledger_path=ledger_path,
        ledger_gate=clean_gate,
    )
    assert result.ledger.expected == 3
    assert result.ledger.file_persisted == 3
    assert result.ledger.pending_commit == 3
    assert result.ledger.versioned_confirmed == 0
    assert result.ledger.failed == 0


def test_apply_plan_blocked_when_pending_commit_gate(monkeypatch, tmp_path):
    from classificacao_procons.migration.dry_run import run_dry_run
    from classificacao_procons.migration.executor import GateCheck, build_execution_plan
    from classificacao_procons.migration.ledger_sync import LedgerStateReport
    from classificacao_procons.migration.models import (
        MondayBoardInventory,
        MondayColumnInfo,
        MondayItemDigest,
    )
    from classificacao_procons.migration.user_mapping import UserMappingPolicy

    class SpyClient:
        def create_item(self, board_id, name, **kwargs):
            return type("Created", (), {"id": "9001"})()

    monkeypatch.setenv("SUNDAY_MIGRATION_ALLOW_APPLY", "1")
    inventory = MondayBoardInventory(
        board_id=KPI_BOARD,
        name="KPI",
        groups={"g2023": "2023"},
        columns=(MondayColumnInfo(id="name", title="Name", type="name"),),
        items=(
            MondayItemDigest(
                item_id="1",
                group_id="g2023",
                created_at="2026-08-01T00:00:00Z",
                updated_at="2026-08-01T00:00:00Z",
            ),
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
        max_items=1,
        mode="apply",
        user_policy=policy,
        sunday_schema_checks=[GateCheck("schema_live_verificado", True)],
    )
    blocked_gate = LedgerStateReport(pending_commit=1)
    try:
        apply_plan(
            plan,
            client=SpyClient(),
            confirm_writes=True,
            snapshot_revalidator=lambda: plan.snapshot_fingerprint,
            ledger_path=tmp_path / "ledger.json",
            ledger_gate=blocked_gate,
        )
    except ExecutorAbort as exc:
        assert "ledger_pending_commit=1" in str(exc)
    else:
        raise AssertionError("expected ExecutorAbort")


def test_post_migration_comment_delta_is_not_migration_miss():
    assert classify_missing_comment_marker(
        update_created_at="2026-08-12T22:12:09.000Z",
        migrated_at="2026-08-12T18:09:52.444065+00:00",
        source_snapshot_timestamp="2026-08-12T18:09:12.542587+00:00",
    ) == "POST_MIGRATION_DELTA"


def test_ledger_write_report_serializes_explicit_semantics():
    report = LedgerWriteReport(
        expected=10,
        file_persisted=10,
        pending_commit=10,
        versioned_confirmed=0,
    )
    payload = ApplyReport(ledger=report).ledger.as_dict()
    assert payload["ledger_file_persisted"] == 10
    assert payload["ledger_versioned_confirmed"] == 0
    assert payload["ledger_pending_commit"] == 10


def test_load_versioned_ledger_from_git_reads_head(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    ledger_path = repo / "docs/migration/ledger.json"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(
        '{"schema_version":1,"records":{"5563754463:1":{"monday_item_id":"1"}}}',
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "ledger"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    records = load_versioned_ledger_from_git(
        repo_root=repo,
        ledger_path=ledger_path,
    )
    assert "5563754463:1" in records
