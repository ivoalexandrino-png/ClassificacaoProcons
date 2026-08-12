"""Dry-run read-only por board: classifica source rows Monday em disposições.

Não escreve em lugar nenhum. Recebe um snapshot de source rows e as regras do
board e produz o ledger + a contabilização, mantendo disposição e **onda** como
dimensões independentes (§6).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from classificacao_procons.sunday.migration.accounting import (
    SourceAccounting,
    build_source_accounting,
)
from classificacao_procons.sunday.migration.dispositions import (
    ALL_DISPOSITIONS,
    Disposition,
)
from classificacao_procons.sunday.migration.ledger import (
    Ledger,
    LedgerEntry,
    SundayNativeEntry,
)


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
    wave: int | None = None
    #: Disposição padrão para linhas sem regra (NO_MATCH → CREATE é normal, §7).
    default_disposition: Disposition = Disposition.CREATE


@dataclass
class BoardDryRun:
    """Resultado read-only de um board."""

    monday_board_id: str
    sunday_board_id: str
    ledger: Ledger
    accounting: SourceAccounting
    wave: int | None = None

    def disposition_counts(self) -> dict[Disposition, int]:
        return self.accounting.counts

    def wave_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.ledger.entries:
            key = f"W{entry.wave}" if entry.wave is not None else "W?"
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


def _classify_row(row: MondaySourceRow, rules: BoardRules) -> LedgerEntry:
    """Precedência: EXCLUDE_TEST > ADOPT > ABSORB > CREATE-id > MANUAL > default (CREATE)."""
    item_id = row.monday_item_id

    if item_id in rules.exclude_test_map:
        return LedgerEntry(
            monday_board_id=rules.monday_board_id,
            monday_item_id=item_id,
            disposition=Disposition.EXCLUDE_TEST,
            reason=rules.exclude_test_map[item_id],
            wave=rules.wave,
        )

    if item_id in rules.adopt_map:
        return LedgerEntry(
            monday_board_id=rules.monday_board_id,
            monday_item_id=item_id,
            disposition=Disposition.ADOPT,
            sunday_board_id=rules.sunday_board_id,
            sunday_item_id=rules.adopt_map[item_id],
            wave=rules.wave,
        )

    if item_id in rules.absorb_map:
        # sunday_item_id do alias é resolvido depois (a partir do canônico).
        return LedgerEntry(
            monday_board_id=rules.monday_board_id,
            monday_item_id=item_id,
            disposition=Disposition.ABSORB,
            sunday_board_id=rules.sunday_board_id,
            canonical_monday_item_id=rules.absorb_map[item_id],
            reason="absorbed_alias",
            wave=rules.wave,
        )

    if item_id in rules.manual_map:
        return LedgerEntry(
            monday_board_id=rules.monday_board_id,
            monday_item_id=item_id,
            disposition=Disposition.MANUAL,
            reason=rules.manual_map[item_id],
            wave=rules.wave,
        )

    # create_ids e o default caem ambos em CREATE (item Sunday novo).
    return LedgerEntry(
        monday_board_id=rules.monday_board_id,
        monday_item_id=item_id,
        disposition=Disposition.CREATE,
        sunday_board_id=rules.sunday_board_id,
        wave=rules.wave,
    )


def _resolve_absorb_targets(ledger: Ledger) -> None:
    """Preenche sunday_item_id dos ABSORB a partir do Sunday item do canônico.

    Se o canônico for ADOPT, o alias aponta para o mesmo Sunday item já existente.
    Se for CREATE (item ainda não criado no dry-run), fica ``None`` — mas o vínculo
    é preservado por ``canonical_monday_item_id``.
    """
    by_monday = {entry.monday_item_id: entry for entry in ledger.entries}
    resolved: list[LedgerEntry] = []
    for entry in ledger.entries:
        if entry.disposition is Disposition.ABSORB and entry.sunday_item_id is None:
            canonical = by_monday.get(entry.canonical_monday_item_id or "")
            if canonical is not None and canonical.sunday_item_id:
                entry = LedgerEntry(
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


def run_board_dry_run(
    *,
    rows: list[MondaySourceRow],
    rules: BoardRules,
    source_snapshot_timestamp: str,
) -> BoardDryRun:
    """Classifica as source rows de um board (read-only)."""
    ledger = Ledger()
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
    return BoardDryRun(
        monday_board_id=rules.monday_board_id,
        sunday_board_id=rules.sunday_board_id,
        ledger=ledger,
        accounting=accounting,
        wave=rules.wave,
    )
