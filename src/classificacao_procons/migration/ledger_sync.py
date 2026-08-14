"""Ledger durável Monday→Sunday: sync plan read-only e validação de persistência."""

from __future__ import annotations

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
)

EvidenceKind = Literal[
    "sunday_monday_id_column",
    "apply_report",
    "ledger_versioned",
]


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
    def idempotent(self) -> bool:
        return (
            not self.records_to_add
            and not self.records_to_modify
            and not self.records_to_delete
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
            "idempotent": self.idempotent,
        }


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
    """PLAN read-only: adiciona mappings live comprovados ausentes do ledger canônico."""
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


def verify_ledger_record_persisted(
    record: dict,
    *,
    ledger_path: str | Path = DEFAULT_LEDGER_PATH,
) -> bool:
    """Read-back do ledger durável após persistência."""
    key = f"{record['monday_board_id']}:{record['monday_item_id']}"
    loaded = load_persistent_ledger(ledger_path).get(key)
    if not loaded:
        return False
    if loaded.get("migration_status") != "migrated":
        return False
    return str(loaded.get("sunday_item_id")) == str(record.get("sunday_item_id"))
