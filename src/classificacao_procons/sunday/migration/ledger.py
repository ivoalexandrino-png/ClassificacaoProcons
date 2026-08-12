"""Ledger da migração: admite N Monday IDs → 1 Sunday item.

Não exige relação 1:1 Monday row ↔ Sunday item. Cada entrada carrega o mínimo
para rastreabilidade (§3). Não grava secrets.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from classificacao_procons.sunday.migration.dispositions import (
    Disposition,
    SundayClassification,
)


class LedgerError(RuntimeError):
    """Entrada de ledger inconsistente com as regras da migração."""


@dataclass(frozen=True)
class LedgerEntry:
    """Uma source row do Monday e sua disposição na migração."""

    monday_board_id: str
    monday_item_id: str
    disposition: Disposition
    sunday_board_id: str | None = None
    sunday_item_id: str | None = None
    #: Preenchido quando ABSORB: o Monday ID canônico que representa o item.
    canonical_monday_item_id: str | None = None
    reason: str | None = None
    #: Onda de migração (dimensão independente da disposição). ``None`` = não atribuída.
    wave: int | None = None

    def __post_init__(self) -> None:
        if self.disposition is Disposition.ADOPT and not self.sunday_item_id:
            raise LedgerError(
                f"ADOPT exige sunday_item_id (monday {self.monday_item_id}).",
            )
        if self.disposition is Disposition.ABSORB and not self.canonical_monday_item_id:
            raise LedgerError(
                f"ABSORB exige canonical_monday_item_id (monday {self.monday_item_id}).",
            )
        if self.disposition is Disposition.ABSORB and (
            self.canonical_monday_item_id == self.monday_item_id
        ):
            raise LedgerError(
                f"ABSORB não pode ser canônico de si mesmo (monday {self.monday_item_id}).",
            )
        if self.disposition is Disposition.EXCLUDE_TEST and not self.reason:
            raise LedgerError(
                f"EXCLUDE_TEST exige reason (monday {self.monday_item_id}).",
            )

    @property
    def creates_sunday_item(self) -> bool:
        return self.disposition is Disposition.CREATE

    @property
    def role(self) -> str:
        """Rótulo de papel para leitura do ledger (canonical vs alias)."""
        if self.disposition is Disposition.ABSORB:
            return "absorbed_alias"
        if self.disposition is Disposition.ADOPT:
            return "canonical/adopt"
        if self.disposition is Disposition.CREATE:
            return "canonical/create"
        return self.disposition.value.lower()


@dataclass(frozen=True)
class SundayNativeEntry:
    """Item nativo do Sunday (sem source row Monday). Fora do denominador Monday."""

    sunday_board_id: str
    sunday_item_id: str
    name: str
    classification: SundayClassification = SundayClassification.SUNDAY_NATIVE
    reason: str | None = None


@dataclass
class Ledger:
    """Coleção de entradas + nativos Sunday, com consultas many↔one."""

    entries: list[LedgerEntry] = field(default_factory=list)
    natives: list[SundayNativeEntry] = field(default_factory=list)

    def add(self, entry: LedgerEntry) -> None:
        self.entries.append(entry)

    def add_native(self, native: SundayNativeEntry) -> None:
        self.natives.append(native)

    def monday_items_for_sunday(self, sunday_item_id: str) -> list[str]:
        """Todos os Monday IDs vinculados a um mesmo Sunday item (canônico + aliases)."""
        return [
            entry.monday_item_id
            for entry in self.entries
            if entry.sunday_item_id == sunday_item_id
        ]

    def canonical_monday_item_for_sunday(self, sunday_item_id: str) -> str | None:
        """Monday ID canônico (não-alias) de um Sunday item — o único da coluna Monday ID."""
        canonical = [
            entry.monday_item_id
            for entry in self.entries
            if entry.sunday_item_id == sunday_item_id
            and entry.disposition is not Disposition.ABSORB
        ]
        if len(canonical) > 1:
            raise LedgerError(
                f"Mais de um Monday canônico para Sunday {sunday_item_id}: {canonical}.",
            )
        return canonical[0] if canonical else None

    def aliases_for_sunday(self, sunday_item_id: str) -> list[str]:
        """Monday IDs absorvidos (aliases) de um Sunday item."""
        return [
            entry.monday_item_id
            for entry in self.entries
            if entry.sunday_item_id == sunday_item_id
            and entry.disposition is Disposition.ABSORB
        ]

    def entry_for_monday(self, monday_item_id: str) -> LedgerEntry | None:
        for entry in self.entries:
            if entry.monday_item_id == monday_item_id:
                return entry
        return None
