"""Testes do núcleo de dry-run da migração (disposições, ledger, conservação, Audiências).

Offline: nenhuma rede, nenhuma escrita no Monday/Sunday.
"""

import pytest

from classificacao_procons.sunday.migration.audiencias import (
    AUDIENCIAS_ADOPT_MAP,
    AUDIENCIAS_MONDAY_BOARD_ID,
    audiencias_rules,
)
from classificacao_procons.sunday.migration.dispositions import Disposition
from classificacao_procons.sunday.migration.dryrun import (
    BoardRules,
    MondaySourceRow,
    run_board_dry_run,
)
from classificacao_procons.sunday.migration.ledger import (
    LedgerEntry,
    LedgerError,
)

_TS = "2026-08-12T00:00:00Z"

# Os 4 técnicos aprovados (§2.3–2.5).
_TECNICO_DAIANE = "12658169524"
_TECNICO_PLACEHOLDER = "12765154145"
_TECNICO_CANONICO = "12774333107"
_REGISTRO_VALIDACAO = "12566356804"


def _audiencias_snapshot_121() -> list[MondaySourceRow]:
    """Snapshot sintético representando as 121 source rows aprovadas.

    117 nominais (8 ADOPT + 109 CREATE) + 4 técnicos (2 ABSORB, 1 CREATE, 1 EXCLUDE_TEST).
    """
    rows: list[MondaySourceRow] = []
    rows += [MondaySourceRow(monday_item_id=mid) for mid in AUDIENCIAS_ADOPT_MAP]  # 8 ADOPT
    rows += [MondaySourceRow(monday_item_id=f"nominal-{i:04d}") for i in range(109)]  # 109 CREATE
    rows += [
        MondaySourceRow(monday_item_id=_TECNICO_DAIANE),
        MondaySourceRow(monday_item_id=_TECNICO_PLACEHOLDER),
        MondaySourceRow(monday_item_id=_TECNICO_CANONICO),
        MondaySourceRow(monday_item_id=_REGISTRO_VALIDACAO),
    ]
    return rows


class TestLedgerValidation:
    def test_adopt_requires_sunday_item_id(self) -> None:
        with pytest.raises(LedgerError, match="ADOPT exige sunday_item_id"):
            LedgerEntry(
                monday_board_id="b",
                monday_item_id="m",
                disposition=Disposition.ADOPT,
            )

    def test_absorb_requires_canonical(self) -> None:
        with pytest.raises(LedgerError, match="ABSORB exige canonical"):
            LedgerEntry(
                monday_board_id="b",
                monday_item_id="m",
                disposition=Disposition.ABSORB,
            )

    def test_absorb_cannot_be_its_own_canonical(self) -> None:
        with pytest.raises(LedgerError, match="canônico de si mesmo"):
            LedgerEntry(
                monday_board_id="b",
                monday_item_id="m",
                disposition=Disposition.ABSORB,
                canonical_monday_item_id="m",
            )

    def test_exclude_test_requires_reason(self) -> None:
        with pytest.raises(LedgerError, match="EXCLUDE_TEST exige reason"):
            LedgerEntry(
                monday_board_id="b",
                monday_item_id="m",
                disposition=Disposition.EXCLUDE_TEST,
            )


class TestAudienciasDispositions:
    def test_adopt_does_not_create_item(self) -> None:
        result = run_board_dry_run(
            rows=[MondaySourceRow("11322933382")],
            rules=audiencias_rules(),
            source_snapshot_timestamp=_TS,
        )
        entry = result.ledger.entry_for_monday("11322933382")
        assert entry is not None
        assert entry.disposition is Disposition.ADOPT
        assert entry.creates_sunday_item is False
        assert entry.sunday_item_id == "7043"

    def test_absorb_does_not_create_and_points_to_canonical(self) -> None:
        # Daiane (ABSORB) + seu nominal canônico (ADOPT 7043) no mesmo snapshot.
        result = run_board_dry_run(
            rows=[MondaySourceRow("11322933382"), MondaySourceRow(_TECNICO_DAIANE)],
            rules=audiencias_rules(),
            source_snapshot_timestamp=_TS,
        )
        alias = result.ledger.entry_for_monday(_TECNICO_DAIANE)
        assert alias is not None
        assert alias.disposition is Disposition.ABSORB
        assert alias.creates_sunday_item is False
        assert alias.canonical_monday_item_id == "11322933382"
        # Resolve para o mesmo Sunday item do canônico (7043).
        assert alias.sunday_item_id == "7043"

    def test_two_monday_ids_map_to_same_sunday_item(self) -> None:
        result = run_board_dry_run(
            rows=[MondaySourceRow("11322933382"), MondaySourceRow(_TECNICO_DAIANE)],
            rules=audiencias_rules(),
            source_snapshot_timestamp=_TS,
        )
        assert set(result.ledger.monday_items_for_sunday("7043")) == {
            "11322933382",
            _TECNICO_DAIANE,
        }
        # Só o canônico vai na coluna Monday ID (§4).
        assert result.ledger.canonical_monday_item_for_sunday("7043") == "11322933382"
        assert result.ledger.aliases_for_sunday("7043") == [_TECNICO_DAIANE]

    def test_placeholder_absorbed_into_canonical_time(self) -> None:
        # 22/10 00:00 (placeholder) ABSORB no 22/10 16:00 (canonical CREATE).
        result = run_board_dry_run(
            rows=[
                MondaySourceRow(_TECNICO_PLACEHOLDER),
                MondaySourceRow(_TECNICO_CANONICO),
            ],
            rules=audiencias_rules(),
            source_snapshot_timestamp=_TS,
        )
        canonical = result.ledger.entry_for_monday(_TECNICO_CANONICO)
        placeholder = result.ledger.entry_for_monday(_TECNICO_PLACEHOLDER)
        assert canonical is not None and canonical.disposition is Disposition.CREATE
        assert placeholder is not None and placeholder.disposition is Disposition.ABSORB
        assert placeholder.canonical_monday_item_id == _TECNICO_CANONICO
        # Canônico ainda não tem Sunday item no dry-run → alias fica sem sunday_item_id,
        # mas o vínculo canônico é preservado.
        assert placeholder.sunday_item_id is None

    def test_exclude_test_counted_without_creating(self) -> None:
        result = run_board_dry_run(
            rows=[MondaySourceRow(_REGISTRO_VALIDACAO)],
            rules=audiencias_rules(),
            source_snapshot_timestamp=_TS,
        )
        entry = result.ledger.entry_for_monday(_REGISTRO_VALIDACAO)
        assert entry is not None
        assert entry.disposition is Disposition.EXCLUDE_TEST
        assert entry.creates_sunday_item is False
        assert entry.reason == "VALIDATION_RECORD"
        # Contabilizado na conservação.
        assert result.accounting.counts[Disposition.EXCLUDE_TEST] == 1
        assert result.accounting.accounted == 1


class TestSundayNativeAndConservation:
    def test_sunday_native_not_in_monday_denominator(self) -> None:
        result = run_board_dry_run(
            rows=_audiencias_snapshot_121(),
            rules=audiencias_rules(),
            source_snapshot_timestamp=_TS,
        )
        # Maria Helena (7065) é nativa: não conta nas 121 source rows.
        assert result.accounting.source_snapshot_total == 121
        assert len(result.ledger.natives) == 1
        assert result.ledger.natives[0].sunday_item_id == "7065"

    def test_source_rows_conservation_121(self) -> None:
        result = run_board_dry_run(
            rows=_audiencias_snapshot_121(),
            rules=audiencias_rules(),
            source_snapshot_timestamp=_TS,
        )
        counts = result.accounting.counts
        assert counts[Disposition.ADOPT] == 8
        assert counts[Disposition.ABSORB] == 2
        assert counts[Disposition.EXCLUDE_TEST] == 1
        assert counts[Disposition.CREATE] == 110  # 109 nominais + 1 técnico canônico
        assert counts[Disposition.MANUAL] == 0
        assert counts[Disposition.ERROR] == 0
        assert result.accounting.accounted == 121
        assert result.accounting.is_conserved is True

    def test_idempotent_adopt_and_absorb(self) -> None:
        rows = _audiencias_snapshot_121()
        first = run_board_dry_run(
            rows=rows, rules=audiencias_rules(), source_snapshot_timestamp=_TS,
        )
        second = run_board_dry_run(
            rows=rows, rules=audiencias_rules(), source_snapshot_timestamp=_TS,
        )
        assert first.as_dict()["dispositions"] == second.as_dict()["dispositions"]
        assert first.ledger.monday_items_for_sunday("7043") == (
            second.ledger.monday_items_for_sunday("7043")
        )


class TestGenericBoardRules:
    def test_no_match_defaults_to_create(self) -> None:
        rules = BoardRules(monday_board_id="b", sunday_board_id="s")
        result = run_board_dry_run(
            rows=[MondaySourceRow("x1"), MondaySourceRow("x2")],
            rules=rules,
            source_snapshot_timestamp=_TS,
        )
        assert result.accounting.counts[Disposition.CREATE] == 2
        assert result.accounting.is_conserved is True

    def test_board_id_matches_approved(self) -> None:
        assert AUDIENCIAS_MONDAY_BOARD_ID == "4443295406"
        assert audiencias_rules().sunday_board_id == "72"
