"""Dry-run read-only por board: classifica source rows Monday em disposições.

Não escreve em lugar nenhum. Recebe um snapshot de source rows e as regras do
board e produz o ledger + a contabilização, mantendo disposição e **onda** como
dimensões independentes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from classificacao_procons.migration.accounting import (
    SourceAccounting,
    build_source_accounting,
)
from classificacao_procons.migration.disposition_ledger import (
    DispositionLedger,
    DispositionLedgerEntry,
    SundayNativeEntry,
)
from classificacao_procons.migration.dispositions import ALL_DISPOSITIONS, Disposition


@dataclass(frozen=True)
class MondaySourceRow:
    """Uma linha de origem do Monday (mínimo para classificar)."""

    monday_item_id: str
    name: str = ""


@dataclass(frozen=True)
class BoardRules:
    """Regras de disposição de um board (dados, sem lógica de negócio embutida)."""

    monday_board_id: str
    sunday_board_id: str
    #: monday_item_id -> sunday_item_id (item Sunday já existente a adotar).
    adopt_map: dict[str, str] = field(default_factory=dict)
    #: monday_item_id -> canonical_monday_item_id (linha auxiliar/duplicada).
    absorb_map: dict[str, str] = field(default_factory=dict)
    #: monday_item_id -> reason (registro de validação/teste).
    exclude_test_map: dict[str, str] = field(default_factory=dict)
    #: IDs que devem criar item explicitamente (ex.: técnico canônico).
    create_ids: frozenset[str] = frozenset()
    #: monday_item_id -> reason (intervenção manual explícita).
    manual_map: dict[str, str] = field(default_factory=dict)
    #: Itens nativos do Sunday (fora do denominador Monday).
    sunday_natives: tuple[SundayNativeEntry, ...] = ()
    #: Onda da migração para este board (dimensão separada da disposição).
    wave: str | None = None
    #: Disposição padrão para linhas sem regra (NO_MATCH → CREATE).
    default_disposition: Disposition = Disposition.CREATE


@dataclass
class BoardDispositionDryRun:
    """Resultado read-only de um board."""

    monday_board_id: str
    sunday_board_id: str
    ledger: DispositionLedger
    accounting: SourceAccounting
    wave: str | None = None

    def disposition_counts(self) -> dict[Disposition, int]:
        return self.accounting.counts

    def wave_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.ledger.entries:
            key = entry.wave if entry.wave is not None else "W?"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def as_dict(self) -> dict[str, object]:
        return {
            "monday_board_id": self.monday_board_id,
            "sunday_board_id": self.sunday_board_id,
            "wave": self.wave,
            "dispositions": {
                d.value: self.accounting.counts.get(d, 0) for d in ALL_DISPOSITIONS
            },
            "wave_counts": self.wave_counts(),
            "sunday_native": len(self.ledger.natives),
            "source_accounting": self.accounting.as_dict(),
        }


def _classify_row(row: MondaySourceRow, rules: BoardRules) -> DispositionLedgerEntry:
    """Precedência: EXCLUDE_TEST > ADOPT > ABSORB > CREATE-id > MANUAL > default."""
    item_id = row.monday_item_id

    if item_id in rules.exclude_test_map:
        return DispositionLedgerEntry(
            monday_board_id=rules.monday_board_id,
            monday_item_id=item_id,
            disposition=Disposition.EXCLUDE_TEST,
            reason=rules.exclude_test_map[item_id],
            wave=rules.wave,
        )

    if item_id in rules.adopt_map:
        return DispositionLedgerEntry(
            monday_board_id=rules.monday_board_id,
            monday_item_id=item_id,
            disposition=Disposition.ADOPT,
            sunday_board_id=rules.sunday_board_id,
            sunday_item_id=rules.adopt_map[item_id],
            wave=rules.wave,
        )

    if item_id in rules.absorb_map:
        return DispositionLedgerEntry(
            monday_board_id=rules.monday_board_id,
            monday_item_id=item_id,
            disposition=Disposition.ABSORB,
            sunday_board_id=rules.sunday_board_id,
            canonical_monday_item_id=rules.absorb_map[item_id],
            reason="absorbed_alias",
            wave=rules.wave,
        )

    if item_id in rules.manual_map:
        return DispositionLedgerEntry(
            monday_board_id=rules.monday_board_id,
            monday_item_id=item_id,
            disposition=Disposition.MANUAL,
            reason=rules.manual_map[item_id],
            wave=rules.wave,
        )

    if item_id in rules.create_ids:
        return DispositionLedgerEntry(
            monday_board_id=rules.monday_board_id,
            monday_item_id=item_id,
            disposition=Disposition.CREATE,
            sunday_board_id=rules.sunday_board_id,
            wave=rules.wave,
        )

    return DispositionLedgerEntry(
        monday_board_id=rules.monday_board_id,
        monday_item_id=item_id,
        disposition=rules.default_disposition,
        sunday_board_id=rules.sunday_board_id,
        wave=rules.wave,
    )


def _resolve_absorb_targets(ledger: DispositionLedger) -> None:
    """Preenche sunday_item_id dos ABSORB a partir do Sunday item do canônico."""
    by_monday = {entry.monday_item_id: entry for entry in ledger.entries}
    resolved: list[DispositionLedgerEntry] = []
    for entry in ledger.entries:
        if entry.disposition is Disposition.ABSORB and entry.sunday_item_id is None:
            canonical = by_monday.get(entry.canonical_monday_item_id or "")
            if canonical is not None and canonical.sunday_item_id:
                entry = DispositionLedgerEntry(
                    monday_board_id=entry.monday_board_id,
                    monday_item_id=entry.monday_item_id,
                    disposition=entry.disposition,
                    sunday_board_id=entry.sunday_board_id,
                    sunday_item_id=canonical.sunday_item_id,
                    canonical_monday_item_id=entry.canonical_monday_item_id,
                    reason=entry.reason,
                    wave=entry.wave,
                )
        resolved.append(entry)
    ledger.entries = resolved


def run_board_disposition_dry_run(
    *,
    rows: list[MondaySourceRow],
    rules: BoardRules,
    source_snapshot_timestamp: str,
) -> BoardDispositionDryRun:
    """Classifica as source rows de um board (read-only)."""
    ledger = DispositionLedger()
    for row in rows:
        ledger.add(_classify_row(row, rules))
    _resolve_absorb_targets(ledger)

    for native in rules.sunday_natives:
        ledger.add_native(native)

    accounting = build_source_accounting(
        ledger=ledger,
        source_snapshot_timestamp=source_snapshot_timestamp,
        source_snapshot_total=len(rows),
    )
    return BoardDispositionDryRun(
        monday_board_id=rules.monday_board_id,
        sunday_board_id=rules.sunday_board_id,
        ledger=ledger,
        accounting=accounting,
        wave=rules.wave,
    )
