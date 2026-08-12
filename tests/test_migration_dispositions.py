"""Testes de disposições, ledger, conservação Audiências e user mapping (25/3/30)."""

from __future__ import annotations

import pytest

from classificacao_procons.migration.audiencias import (
    AUDIENCIAS_ADOPT_MAP,
    AUDIENCIAS_MONDAY_BOARD_ID,
    AUDIENCIAS_SOURCE_SNAPSHOT_TOTAL,
    audiencias_rules,
)
from classificacao_procons.migration.board_disposition import (
    BoardRules,
    MondaySourceRow,
    run_board_disposition_dry_run,
)
from classificacao_procons.migration.disposition_ledger import (
    DispositionLedgerEntry,
    LedgerError,
)
from classificacao_procons.migration.dispositions import Disposition
from classificacao_procons.migration.dry_run import run_dry_run
from classificacao_procons.migration.mappings import WAVE1_TARGETS, group_rule
from classificacao_procons.migration.models import MondayBoardInventory, MondayItemDigest
from classificacao_procons.migration.user_mapping import (
    UserMappingPolicy,
    classify_monday_user,
    load_user_mapping_policy,
    people_assignment_requires_manual,
)

_TS = "2026-08-12T00:00:00Z"

_TECNICO_DAIANE = "12658169524"
_TECNICO_PLACEHOLDER = "12765154145"
_TECNICO_CANONICO = "12774333107"
_REGISTRO_VALIDACAO = "12566356804"


def _audiencias_snapshot_121() -> list[MondaySourceRow]:
    rows: list[MondaySourceRow] = []
    rows += [MondaySourceRow(monday_item_id=mid) for mid in AUDIENCIAS_ADOPT_MAP]
    rows += [MondaySourceRow(monday_item_id=f"nominal-{i:04d}") for i in range(109)]
    rows += [
        MondaySourceRow(monday_item_id=_TECNICO_DAIANE),
        MondaySourceRow(monday_item_id=_TECNICO_PLACEHOLDER),
        MondaySourceRow(monday_item_id=_TECNICO_CANONICO),
        MondaySourceRow(monday_item_id=_REGISTRO_VALIDACAO),
    ]
    return rows


@pytest.fixture
def user_policy_25_3_30() -> UserMappingPolicy:
    return UserMappingPolicy(
        exact_match_ids=frozenset(f"exact-{index}" for index in range(25)),
        active_unmatched_ids=frozenset(f"active-{index}" for index in range(3)),
        deactivated_ids=frozenset(f"deact-{index}" for index in range(30)),
    )


class TestLedgerValidation:
    def test_adopt_requires_sunday_item_id(self) -> None:
        with pytest.raises(LedgerError, match="ADOPT exige sunday_item_id"):
            DispositionLedgerEntry(
                monday_board_id="b",
                monday_item_id="m",
                disposition=Disposition.ADOPT,
            )

    def test_absorb_requires_canonical(self) -> None:
        with pytest.raises(LedgerError, match="ABSORB exige canonical"):
            DispositionLedgerEntry(
                monday_board_id="b",
                monday_item_id="m",
                disposition=Disposition.ABSORB,
            )

    def test_absorb_cannot_be_its_own_canonical(self) -> None:
        with pytest.raises(LedgerError, match="canônico de si mesmo"):
            DispositionLedgerEntry(
                monday_board_id="b",
                monday_item_id="m",
                disposition=Disposition.ABSORB,
                canonical_monday_item_id="m",
            )

    def test_exclude_test_requires_reason(self) -> None:
        with pytest.raises(LedgerError, match="EXCLUDE_TEST exige reason"):
            DispositionLedgerEntry(
                monday_board_id="b",
                monday_item_id="m",
                disposition=Disposition.EXCLUDE_TEST,
            )


class TestAudienciasDispositions:
    def test_adopt_does_not_create_item(self) -> None:
        result = run_board_disposition_dry_run(
            rows=[MondaySourceRow("11322933382")],
            rules=audiencias_rules(),
            source_snapshot_timestamp=_TS,
        )
        entry = result.ledger.entry_for_monday("11322933382")
        assert entry is not None
        assert entry.disposition is Disposition.ADOPT
        assert entry.creates_sunday_item is False
        assert entry.sunday_item_id == "7043"
        assert entry.wave == "WAVE_1"

    def test_absorb_does_not_create_and_points_to_canonical(self) -> None:
        result = run_board_disposition_dry_run(
            rows=[MondaySourceRow("11322933382"), MondaySourceRow(_TECNICO_DAIANE)],
            rules=audiencias_rules(),
            source_snapshot_timestamp=_TS,
        )
        alias = result.ledger.entry_for_monday(_TECNICO_DAIANE)
        assert alias is not None
        assert alias.disposition is Disposition.ABSORB
        assert alias.creates_sunday_item is False
        assert alias.canonical_monday_item_id == "11322933382"
        assert alias.sunday_item_id == "7043"

    def test_two_monday_ids_map_to_same_sunday_item(self) -> None:
        result = run_board_disposition_dry_run(
            rows=[MondaySourceRow("11322933382"), MondaySourceRow(_TECNICO_DAIANE)],
            rules=audiencias_rules(),
            source_snapshot_timestamp=_TS,
        )
        assert set(result.ledger.monday_items_for_sunday("7043")) == {
            "11322933382",
            _TECNICO_DAIANE,
        }
        assert result.ledger.canonical_monday_item_for_sunday("7043") == "11322933382"
        assert result.ledger.aliases_for_sunday("7043") == [_TECNICO_DAIANE]

    def test_placeholder_absorbed_into_canonical_time(self) -> None:
        result = run_board_disposition_dry_run(
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
        assert placeholder.sunday_item_id is None

    def test_exclude_test_counted_without_creating(self) -> None:
        result = run_board_disposition_dry_run(
            rows=[MondaySourceRow(_REGISTRO_VALIDACAO)],
            rules=audiencias_rules(),
            source_snapshot_timestamp=_TS,
        )
        entry = result.ledger.entry_for_monday(_REGISTRO_VALIDACAO)
        assert entry is not None
        assert entry.disposition is Disposition.EXCLUDE_TEST
        assert entry.creates_sunday_item is False
        assert entry.reason == "VALIDATION_RECORD"
        assert result.accounting.counts[Disposition.EXCLUDE_TEST] == 1
        assert result.accounting.accounted == 1

    def test_wave_and_disposition_are_independent(self) -> None:
        rules_wave_1 = audiencias_rules(wave="WAVE_1")
        rules_wave_2 = audiencias_rules(wave="WAVE_2")
        adopt_w1 = run_board_disposition_dry_run(
            rows=[MondaySourceRow("11322933382")],
            rules=rules_wave_1,
            source_snapshot_timestamp=_TS,
        )
        adopt_w2 = run_board_disposition_dry_run(
            rows=[MondaySourceRow("11322933382")],
            rules=rules_wave_2,
            source_snapshot_timestamp=_TS,
        )
        assert adopt_w1.ledger.entry_for_monday("11322933382").disposition is Disposition.ADOPT
        assert adopt_w2.ledger.entry_for_monday("11322933382").disposition is Disposition.ADOPT
        assert adopt_w1.ledger.entry_for_monday("11322933382").wave == "WAVE_1"
        assert adopt_w2.ledger.entry_for_monday("11322933382").wave == "WAVE_2"


class TestSundayNativeAndConservation:
    def test_sunday_native_not_in_monday_denominator(self) -> None:
        result = run_board_disposition_dry_run(
            rows=_audiencias_snapshot_121(),
            rules=audiencias_rules(),
            source_snapshot_timestamp=_TS,
        )
        assert result.accounting.source_snapshot_total == 121
        assert len(result.ledger.natives) == 1
        assert result.ledger.natives[0].sunday_item_id == "7065"

    def test_source_rows_conservation_121(self) -> None:
        result = run_board_disposition_dry_run(
            rows=_audiencias_snapshot_121(),
            rules=audiencias_rules(),
            source_snapshot_timestamp=_TS,
        )
        counts = result.accounting.counts
        assert counts[Disposition.ADOPT] == 8
        assert counts[Disposition.ABSORB] == 2
        assert counts[Disposition.EXCLUDE_TEST] == 1
        assert counts[Disposition.CREATE] == 110
        assert counts[Disposition.MANUAL] == 0
        assert counts[Disposition.ERROR] == 0
        assert result.accounting.accounted == AUDIENCIAS_SOURCE_SNAPSHOT_TOTAL
        assert result.accounting.is_conserved is True

    def test_idempotent_adopt_and_absorb(self) -> None:
        rows = _audiencias_snapshot_121()
        first = run_board_disposition_dry_run(
            rows=rows, rules=audiencias_rules(), source_snapshot_timestamp=_TS,
        )
        second = run_board_disposition_dry_run(
            rows=rows, rules=audiencias_rules(), source_snapshot_timestamp=_TS,
        )
        assert first.as_dict()["dispositions"] == second.as_dict()["dispositions"]


class TestGenericBoardRules:
    def test_no_match_defaults_to_create(self) -> None:
        rules = BoardRules(monday_board_id="b", sunday_board_id="s")
        result = run_board_disposition_dry_run(
            rows=[MondaySourceRow("x1"), MondaySourceRow("x2")],
            rules=rules,
            source_snapshot_timestamp=_TS,
        )
        assert result.accounting.counts[Disposition.CREATE] == 2
        assert result.accounting.is_conserved is True

    def test_board_id_matches_approved(self) -> None:
        assert AUDIENCIAS_MONDAY_BOARD_ID == "4443295406"
        assert audiencias_rules().sunday_board_id == "72"


class TestUserMappingPolicy:
    def test_should_load_28_active_and_30_deactivated_from_json(self) -> None:
        policy = load_user_mapping_policy("docs/monday-user-identities-2026-08-11.json")
        assert len(policy.known_active_ids) == 28
        assert len(policy.deactivated_ids) == 30

    def test_should_assign_exact_match_without_manual(self, user_policy_25_3_30) -> None:
        assert classify_monday_user("exact-0", user_policy_25_3_30) == "exact"
        assert not people_assignment_requires_manual("exact-0", user_policy_25_3_30)

    def test_should_keep_active_unmatched_empty_without_manual(
        self, user_policy_25_3_30,
    ) -> None:
        assert classify_monday_user("active-0", user_policy_25_3_30) == "active_unmatched"
        assert not people_assignment_requires_manual("active-0", user_policy_25_3_30)

    def test_should_keep_deactivated_empty_without_manual(
        self, user_policy_25_3_30,
    ) -> None:
        assert classify_monday_user("deact-0", user_policy_25_3_30) == "deactivated"
        assert not people_assignment_requires_manual("deact-0", user_policy_25_3_30)

    def test_should_manual_only_for_unknown_user(self, user_policy_25_3_30) -> None:
        assert classify_monday_user("brand-new", user_policy_25_3_30) == "unknown"
        assert people_assignment_requires_manual("brand-new", user_policy_25_3_30)

    def test_should_not_manual_deactivated_in_global_dry_run(
        self, user_policy_25_3_30,
    ) -> None:
        inventory = MondayBoardInventory(
            board_id="5301515799",
            name="Controle",
            groups={"g_jan": "Contratos Pendentes de Assinatura Jan"},
            columns=(),
            items=(
                MondayItemDigest(
                    item_id="1",
                    group_id="g_jan",
                    created_at="2026-01-10T00:00:00Z",
                    updated_at="2026-01-10T00:00:00Z",
                    people_ids=("deact-0",),
                ),
            ),
        )
        report, _plans, _pulled = run_dry_run(
            {"5301515799": inventory},
            {},
            user_policy=user_policy_25_3_30,
        )
        assert report.items[0].classification == "WAVE_1_READY"


class TestGlobalEngineRegression:
    def test_should_keep_wave1_targets_for_eight_boards(self) -> None:
        assert len(WAVE1_TARGETS) == 8

    def test_should_keep_group_rules_for_known_groups(self) -> None:
        assert group_rule("5301515799", "Assinados") == ("preservar", "terminal")
        assert group_rule("4443295406", "audiencias (procons e processos)") is not None
