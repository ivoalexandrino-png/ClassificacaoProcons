"""Dimensão de disposição da migração (independente da onda).

Classifica cada source row do Monday em CREATE/ADOPT/ABSORB/EXCLUDE_TEST/MANUAL/
ERROR e produz `LedgerRecord`s (que admitem N Monday IDs → 1 Sunday item) + a
conservação das source rows. Read-only: nada escreve no Monday ou no Sunday.

A disposição é ORTOGONAL à onda (`Classification`): não substitui uma pela outra.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from classificacao_procons.migration.models import (
    ALL_DISPOSITIONS,
    Disposition,
    LedgerRecord,
    SundayNativeRecord,
)


class DispositionError(RuntimeError):
    """Regra de disposição inconsistente."""


@dataclass(frozen=True)
class MondaySourceRow:
    """Linha de origem do Monday (mínimo para classificar disposição)."""

    monday_item_id: str
    name: str = ""


@dataclass(frozen=True)
class BoardDispositionRules:
    """Regras de disposição de um board (dados, sem lógica embutida)."""

    monday_board_id: str
    sunday_board_id: str
    adopt_map: dict[str, str] = field(default_factory=dict)  # monday_id -> sunday_id
    absorb_map: dict[str, str] = field(default_factory=dict)  # monday_id -> canonical_monday_id
    exclude_test_map: dict[str, str] = field(default_factory=dict)  # monday_id -> reason
    create_ids: frozenset[str] = frozenset()
    manual_map: dict[str, str] = field(default_factory=dict)  # monday_id -> reason
    sunday_natives: tuple[SundayNativeRecord, ...] = ()
    wave: int | None = None


@dataclass(frozen=True)
class SourceAccounting:
    """Conservação das source rows do snapshot (§5).

    CREATE + ADOPT + ABSORB + EXCLUDE_TEST + MANUAL + ERROR = TOTAL SOURCE ROWS.
    Nativos Sunday (SUNDAY_NATIVE) não entram no denominador.
    """

    source_snapshot_timestamp: str
    source_snapshot_total: int
    counts: dict[Disposition, int]
    sunday_native_count: int = 0

    @property
    def accounted(self) -> int:
        return sum(self.counts.values())

    @property
    def is_conserved(self) -> bool:
        return self.accounted == self.source_snapshot_total

    def as_dict(self) -> dict[str, object]:
        return {
            "source_snapshot_timestamp": self.source_snapshot_timestamp,
            "source_snapshot_total": self.source_snapshot_total,
            "accounted": self.accounted,
            "conserved": self.is_conserved,
            "counts": {d: self.counts.get(d, 0) for d in ALL_DISPOSITIONS},
            "sunday_native": self.sunday_native_count,
        }


@dataclass
class DispositionDryRun:
    """Resultado read-only da classificação de disposição de um board."""

    monday_board_id: str
    sunday_board_id: str
    records: list[LedgerRecord]
    natives: list[SundayNativeRecord]
    accounting: SourceAccounting
    wave: int | None = None

    def record_for(self, monday_item_id: str) -> LedgerRecord | None:
        for record in self.records:
            if record.monday_item_id == monday_item_id:
                return record
        return None

    def monday_items_for_sunday(self, sunday_item_id: str) -> list[str]:
        return [r.monday_item_id for r in self.records if r.sunday_item_id == sunday_item_id]

    def canonical_monday_item_for_sunday(self, sunday_item_id: str) -> str | None:
        canonical = [
            r.monday_item_id
            for r in self.records
            if r.sunday_item_id == sunday_item_id and r.disposition != "ABSORB"
        ]
        if len(canonical) > 1:
            raise DispositionError(
                f"Mais de um Monday canônico para Sunday {sunday_item_id}: {canonical}.",
            )
        return canonical[0] if canonical else None

    def aliases_for_sunday(self, sunday_item_id: str) -> list[str]:
        return [
            r.monday_item_id
            for r in self.records
            if r.sunday_item_id == sunday_item_id and r.disposition == "ABSORB"
        ]

    def as_dict(self) -> dict[str, object]:
        return {
            "monday_board_id": self.monday_board_id,
            "sunday_board_id": self.sunday_board_id,
            "wave": self.wave,
            "dispositions": {d: self.accounting.counts.get(d, 0) for d in ALL_DISPOSITIONS},
            "sunday_native": len(self.natives),
            "source_accounting": self.accounting.as_dict(),
        }


def _classify_row(row: MondaySourceRow, rules: BoardDispositionRules) -> LedgerRecord:
    """Precedência: EXCLUDE_TEST > ADOPT > ABSORB > CREATE-id > MANUAL > default (CREATE)."""
    item_id = row.monday_item_id
    base = {
        "monday_board_id": rules.monday_board_id,
        "monday_item_id": item_id,
        "sunday_board_id": rules.sunday_board_id,
    }

    if item_id in rules.exclude_test_map:
        return LedgerRecord(
            **base,
            sunday_item_id=None,
            disposition="EXCLUDE_TEST",
            disposition_reason=rules.exclude_test_map[item_id],
            migration_status="skipped",
        )

    if item_id in rules.adopt_map:
        return LedgerRecord(
            **base,
            sunday_item_id=rules.adopt_map[item_id],
            disposition="ADOPT",
        )

    if item_id in rules.absorb_map:
        # sunday_item_id do alias é resolvido depois (a partir do canônico).
        return LedgerRecord(
            **base,
            sunday_item_id=None,
            disposition="ABSORB",
            canonical_monday_item_id=rules.absorb_map[item_id],
            disposition_reason="absorbed_alias",
        )

    if item_id in rules.manual_map:
        return LedgerRecord(
            **base,
            sunday_item_id=None,
            disposition="MANUAL",
            disposition_reason=rules.manual_map[item_id],
            migration_status="skipped",
        )

    return LedgerRecord(**base, sunday_item_id=None, disposition="CREATE")


def _resolve_absorb_targets(records: list[LedgerRecord]) -> list[LedgerRecord]:
    """Preenche sunday_item_id dos ABSORB a partir do Sunday item do canônico (se houver)."""
    by_monday = {r.monday_item_id: r for r in records}
    resolved: list[LedgerRecord] = []
    for record in records:
        if record.disposition == "ABSORB" and record.sunday_item_id is None:
            canonical = by_monday.get(record.canonical_monday_item_id or "")
            if canonical is not None and canonical.sunday_item_id:
                from dataclasses import replace

                record = replace(record, sunday_item_id=canonical.sunday_item_id)
        resolved.append(record)
    return resolved


def _count_dispositions(records: list[LedgerRecord]) -> dict[Disposition, int]:
    counts: dict[Disposition, int] = {d: 0 for d in ALL_DISPOSITIONS}
    for record in records:
        if record.disposition is not None:
            counts[record.disposition] += 1
    return counts


def classify_board_dispositions(
    *,
    rows: list[MondaySourceRow],
    rules: BoardDispositionRules,
    source_snapshot_timestamp: str,
) -> DispositionDryRun:
    """Classifica as source rows de um board por disposição (read-only)."""
    records = [_classify_row(row, rules) for row in rows]
    records = _resolve_absorb_targets(records)
    natives = list(rules.sunday_natives)

    accounting = SourceAccounting(
        source_snapshot_timestamp=source_snapshot_timestamp,
        source_snapshot_total=len(rows),
        counts=_count_dispositions(records),
        sunday_native_count=len(natives),
    )
    return DispositionDryRun(
        monday_board_id=rules.monday_board_id,
        sunday_board_id=rules.sunday_board_id,
        records=records,
        natives=natives,
        accounting=accounting,
        wave=rules.wave,
    )
