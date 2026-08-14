"""Ledger durável Monday→Sunday: sync plan, estado versionado e validação."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from classificacao_procons.migration.apply_writer import (
    build_sunday_monday_id_index,
    parse_monday_item_id_from_column_value,
)
from classificacao_procons.migration.executor import (
    BOARD_ALLOWLIST,
    DEFAULT_LEDGER_PATH,
    load_persistent_ledger,
    persist_ledger_record,
)

EvidenceKind = Literal[
    "sunday_monday_id_column",
    "apply_report",
    "ledger_versioned",
]


def ledger_record_key(record: dict) -> str:
    return f"{record['monday_board_id']}:{record['monday_item_id']}"


def resolve_repo_root(start: Path | None = None) -> Path:
    candidate = (start or Path.cwd()).resolve()
    for path in (candidate, *candidate.parents):
        if (path / ".git").is_dir():
            return path
    return candidate


def load_versioned_ledger_from_git(
    *,
    repo_root: Path | None = None,
    ref: str = "HEAD",
    ledger_path: str | Path = DEFAULT_LEDGER_PATH,
) -> dict[str, dict]:
    """Ledger canônico versionado em Git (HEAD/main), não o working tree."""
    root = resolve_repo_root(repo_root)
    ledger_file = Path(ledger_path)
    try:
        relative = ledger_file.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = ledger_file.as_posix()
    try:
        raw = subprocess.check_output(
            ["git", "show", f"{ref}:{relative}"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    payload = json.loads(raw.decode("utf-8"))
    return payload.get("records", {})


def records_equivalent(left: dict, right: dict) -> bool:
    keys = (
        "monday_board_id",
        "monday_item_id",
        "sunday_board_id",
        "sunday_item_id",
        "migration_status",
    )
    return all(str(left.get(key, "")) == str(right.get(key, "")) for key in keys)


@dataclass(frozen=True)
class LiveProvenMapping:
    monday_board_id: str
    monday_item_id: str
    sunday_board_id: str
    sunday_item_id: str
    monday_id_column_raw: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class LedgerSyncAddition:
    monday_board_id: str
    monday_item_id: str
    sunday_board_id: str
    sunday_item_id: str
    disposition: str
    canonical_monday_item_id: str | None
    wave: str
    migration_status: str
    provenance: tuple[str, ...]


@dataclass
class LedgerSyncPlan:
    canonical_path: str
    records_canonical_before: int
    live_proven_mappings: int
    records_to_add: list[LedgerSyncAddition] = field(default_factory=list)
    records_to_modify: list[dict[str, object]] = field(default_factory=list)
    records_to_delete: list[str] = field(default_factory=list)
    duplicate_mappings: int = 0
    duplicate_sunday_targets: int = 0
    canonical_conflicts: int = 0
    orphan_mappings: int = 0

    @property
    def changes_required(self) -> bool:
        return bool(self.records_to_add or self.records_to_modify or self.records_to_delete)

    @property
    def sync_idempotent(self) -> bool:
        return (
            not self.changes_required
            and self.duplicate_mappings == 0
            and self.duplicate_sunday_targets == 0
            and self.canonical_conflicts == 0
            and self.orphan_mappings == 0
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "canonical_path": self.canonical_path,
            "records_canonical_before": self.records_canonical_before,
            "live_proven_mappings": self.live_proven_mappings,
            "records_to_add": [
                {
                    "monday_board_id": item.monday_board_id,
                    "monday_item_id": item.monday_item_id,
                    "sunday_board_id": item.sunday_board_id,
                    "sunday_item_id": item.sunday_item_id,
                    "board": item.monday_board_id,
                    "disposition": item.disposition,
                    "canonical_monday_item_id": item.canonical_monday_item_id,
                    "provenance": list(item.provenance),
                }
                for item in self.records_to_add
            ],
            "records_to_modify": self.records_to_modify,
            "records_to_delete": self.records_to_delete,
            "duplicate_mappings": self.duplicate_mappings,
            "duplicate_sunday_targets": self.duplicate_sunday_targets,
            "canonical_conflicts": self.canonical_conflicts,
            "orphan_mappings": self.orphan_mappings,
            "changes_required": self.changes_required,
            "sync_idempotent": self.sync_idempotent,
        }


@dataclass
class LedgerStateReport:
    """Estado do ledger: filesystem local vs Git versionado vs live Sunday."""

    git_head_records: int = 0
    local_file_records: int = 0
    live_proven_mappings: int = 0
    file_persisted: int = 0
    pending_sync: int = 0
    pending_commit: int = 0
    versioned_confirmed: int = 0
    failed: int = 0
    pending_sync_keys: list[str] = field(default_factory=list)
    pending_commit_keys: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "ledger_expected": 0,
            "ledger_file_persisted": self.file_persisted,
            "ledger_versioned_confirmed": self.versioned_confirmed,
            "ledger_pending_sync": self.pending_sync,
            "ledger_pending_commit": self.pending_commit,
            "ledger_failed": self.failed,
            "git_head_records": self.git_head_records,
            "local_file_records": self.local_file_records,
            "live_proven_mappings": self.live_proven_mappings,
            "pending_sync_keys": list(self.pending_sync_keys),
            "pending_commit_keys": list(self.pending_commit_keys),
        }


def assess_ledger_state(
    *,
    live_mappings: list[LiveProvenMapping],
    ledger_path: str | Path = DEFAULT_LEDGER_PATH,
    repo_root: Path | None = None,
    git_ref: str = "HEAD",
) -> LedgerStateReport:
    """Compara live Sunday, arquivo local canônico e Git HEAD."""
    local_ledger = load_persistent_ledger(ledger_path)
    git_ledger = load_versioned_ledger_from_git(
        repo_root=repo_root,
        ref=git_ref,
        ledger_path=ledger_path,
    )
    report = LedgerStateReport(
        git_head_records=len(git_ledger),
        local_file_records=len(local_ledger),
        live_proven_mappings=len(live_mappings),
    )

    for mapping in live_mappings:
        key = f"{mapping.monday_board_id}:{mapping.monday_item_id}"
        local = local_ledger.get(key)
        git = git_ledger.get(key)
        expected = {
            "monday_board_id": mapping.monday_board_id,
            "monday_item_id": mapping.monday_item_id,
            "sunday_board_id": mapping.sunday_board_id,
            "sunday_item_id": mapping.sunday_item_id,
            "migration_status": "migrated",
        }
        if local is None or not records_equivalent(local, expected):
            report.pending_sync += 1
            report.pending_sync_keys.append(key)
            continue
        if git is None or not records_equivalent(git, expected):
            report.pending_commit += 1
            report.pending_commit_keys.append(key)
            continue
        report.versioned_confirmed += 1

    for key, local in local_ledger.items():
        git = git_ledger.get(key)
        if git is None or not records_equivalent(local, git):
            if key not in report.pending_commit_keys:
                report.pending_commit += 1
                report.pending_commit_keys.append(key)

    return report


def validate_apply_ledger_gate(report: LedgerStateReport) -> list[str]:
    """Fail-closed: próximo APPLY bloqueado se ledger canônico estiver incompleto."""
    failures: list[str] = []
    if report.pending_sync > 0:
        failures.append(
            f"ledger_pending_sync={report.pending_sync} "
            "(mapping live comprovado ausente do arquivo canônico local)",
        )
    if report.pending_commit > 0:
        failures.append(
            f"ledger_pending_commit={report.pending_commit} "
            "(arquivo local diverge de Git HEAD — commit/merge do ledger obrigatório)",
        )
    if report.failed > 0:
        failures.append(f"ledger_failed={report.failed}")
    return failures


def discover_live_proven_mappings(
    *,
    client,
    sunday_snapshots: dict[str, object],
    monday_id_column_ids: dict[str, str],
) -> list[LiveProvenMapping]:
    """Deriva mappings Monday→Sunday apenas da coluna Monday ID live (sem inferência por nome)."""
    proven: list[LiveProvenMapping] = []
    for monday_board_id, sunday_board_id in BOARD_ALLOWLIST.items():
        monday_id_column_id = monday_id_column_ids[sunday_board_id]
        index = build_sunday_monday_id_index(
            client,
            board_id=sunday_board_id,
            monday_id_column_id=monday_id_column_id,
        )
        for item in client.list_items(sunday_board_id).items:
            raw = client.get_value(item.id, monday_id_column_id)
            if raw is None:
                continue
            raw_text = str(raw).strip()
            if not raw_text:
                continue
            monday_item_id = parse_monday_item_id_from_column_value(raw)
            if not monday_item_id:
                continue
            expected_raw_prefix = f"{monday_board_id}/"
            if not raw_text.startswith(expected_raw_prefix):
                continue
            indexed_sunday_id = index.get(monday_item_id)
            if indexed_sunday_id != item.id:
                continue
            proven.append(
                LiveProvenMapping(
                    monday_board_id=monday_board_id,
                    monday_item_id=monday_item_id,
                    sunday_board_id=sunday_board_id,
                    sunday_item_id=item.id,
                    monday_id_column_raw=raw_text,
                    evidence=("sunday_monday_id_column",),
                ),
            )
    return proven


def build_ledger_sync_plan(
    *,
    canonical_ledger: dict[str, dict] | None = None,
    live_mappings: list[LiveProvenMapping],
    ledger_path: str = DEFAULT_LEDGER_PATH,
    apply_evidence: dict[str, dict[str, str]] | None = None,
) -> LedgerSyncPlan:
    """PLAN read-only: adiciona mappings live comprovados ausentes do ledger canônico local."""
    if canonical_ledger is not None:
        ledger = canonical_ledger
    else:
        ledger = load_persistent_ledger(ledger_path)
    plan = LedgerSyncPlan(
        canonical_path=str(ledger_path),
        records_canonical_before=len(ledger),
        live_proven_mappings=len(live_mappings),
    )
    seen_keys: set[str] = set()
    seen_sunday: set[tuple[str, str]] = set()
    for mapping in live_mappings:
        key = f"{mapping.monday_board_id}:{mapping.monday_item_id}"
        sunday_key = (mapping.sunday_board_id, mapping.sunday_item_id)
        if key in seen_keys:
            plan.duplicate_mappings += 1
            continue
        if sunday_key in seen_sunday:
            plan.duplicate_sunday_targets += 1
            continue
        seen_keys.add(key)
        seen_sunday.add(sunday_key)

        existing = ledger.get(key)
        if existing:
            if str(existing.get("sunday_item_id")) != mapping.sunday_item_id:
                plan.canonical_conflicts += 1
            continue

        provenance = list(mapping.evidence)
        evidence = (apply_evidence or {}).get(mapping.monday_item_id)
        if evidence:
            provenance.extend(
                f"{field}={value}"
                for field, value in sorted(evidence.items())
                if value
            )
        plan.records_to_add.append(
            LedgerSyncAddition(
                monday_board_id=mapping.monday_board_id,
                monday_item_id=mapping.monday_item_id,
                sunday_board_id=mapping.sunday_board_id,
                sunday_item_id=mapping.sunday_item_id,
                disposition="CREATE",
                canonical_monday_item_id=None,
                wave="WAVE_1",
                migration_status="migrated",
                provenance=tuple(provenance),
            ),
        )
    return plan


def apply_ledger_sync_plan(
    plan: LedgerSyncPlan,
    *,
    ledger_path: str | Path,
) -> int:
    """Persiste additions do sync plan no arquivo local (sem git commit)."""
    written = 0
    for addition in plan.records_to_add:
        record = {
            "monday_board_id": addition.monday_board_id,
            "monday_item_id": addition.monday_item_id,
            "sunday_board_id": addition.sunday_board_id,
            "sunday_item_id": addition.sunday_item_id,
            "wave": addition.wave,
            "disposition": addition.disposition,
            "canonical_monday_item_id": addition.canonical_monday_item_id,
            "reason": None,
            "migration_status": addition.migration_status,
            "migrated_at": None,
            "source_snapshot_timestamp": None,
        }
        persist_ledger_record(record, path=ledger_path)
        if not verify_ledger_record_persisted(record, ledger_path=ledger_path):
            raise RuntimeError(
                f"Ledger file persistence failed for {addition.monday_item_id}",
            )
        written += 1
    return written


def verify_ledger_record_persisted(
    record: dict,
    *,
    ledger_path: str | Path = DEFAULT_LEDGER_PATH,
) -> bool:
    """Read-back do arquivo local canônico após persistência."""
    key = ledger_record_key(record)
    loaded = load_persistent_ledger(ledger_path).get(key)
    if not loaded:
        return False
    if loaded.get("migration_status") != "migrated":
        return False
    return str(loaded.get("sunday_item_id")) == str(record.get("sunday_item_id"))


def classify_ledger_write_outcome(
    record: dict,
    *,
    ledger_path: str | Path,
    repo_root: Path | None = None,
    git_ref: str = "HEAD",
) -> Literal["file_persisted", "versioned_confirmed", "pending_commit", "failed"]:
    if not verify_ledger_record_persisted(record, ledger_path=ledger_path):
        return "failed"
    git_ledger = load_versioned_ledger_from_git(
        repo_root=repo_root,
        ref=git_ref,
        ledger_path=ledger_path,
    )
    git_record = git_ledger.get(ledger_record_key(record))
    if git_record is not None and records_equivalent(git_record, record):
        return "versioned_confirmed"
    return "pending_commit"
