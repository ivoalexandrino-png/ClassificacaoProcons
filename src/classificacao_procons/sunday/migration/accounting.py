"""Conservação de source rows do snapshot (§5) — separada de itens criados/adotados."""

from __future__ import annotations

from dataclasses import dataclass

from classificacao_procons.sunday.migration.dispositions import (
    ALL_DISPOSITIONS,
    Disposition,
)
from classificacao_procons.sunday.migration.ledger import Ledger


@dataclass(frozen=True)
class SourceAccounting:
    """Contabilização das source rows Monday de um snapshot.

    Regra obrigatória (§5): a soma de CREATE + ADOPT + ABSORB + EXCLUDE_TEST +
    MANUAL + ERROR = TOTAL SOURCE ROWS. Nativos Sunday (SUNDAY_NATIVE) **não**
    entram no denominador.
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

    @property
    def missing(self) -> int:
        return self.source_snapshot_total - self.accounted

    def as_dict(self) -> dict[str, object]:
        return {
            "source_snapshot_timestamp": self.source_snapshot_timestamp,
            "source_snapshot_total": self.source_snapshot_total,
            "accounted": self.accounted,
            "conserved": self.is_conserved,
            "counts": {d.value: self.counts.get(d, 0) for d in ALL_DISPOSITIONS},
            "sunday_native": self.sunday_native_count,
        }


def count_dispositions(ledger: Ledger) -> dict[Disposition, int]:
    counts: dict[Disposition, int] = {disposition: 0 for disposition in ALL_DISPOSITIONS}
    for entry in ledger.entries:
        counts[entry.disposition] += 1
    return counts


def build_source_accounting(
    *,
    ledger: Ledger,
    source_snapshot_timestamp: str,
    source_snapshot_total: int,
) -> SourceAccounting:
    return SourceAccounting(
        source_snapshot_timestamp=source_snapshot_timestamp,
        source_snapshot_total=source_snapshot_total,
        counts=count_dispositions(ledger),
        sunday_native_count=len(ledger.natives),
    )
