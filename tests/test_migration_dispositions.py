"""Testes da dimensão disposição da migração (Audiências) — offline, sem escrita."""

from collections import Counter

from classificacao_procons.migration.audiencias import (
    AUDIENCIAS_ADOPT_MAP,
    AUDIENCIAS_MONDAY_BOARD_ID,
    audiencias_disposition_rules,
)
from classificacao_procons.migration.dispositions import (
    BoardDispositionRules,
    MondaySourceRow,
    classify_board_dispositions,
)

_TS = "2026-08-12T00:00:00Z"
_TECNICO_DAIANE = "12658169524"
_TECNICO_PLACEHOLDER = "12765154145"
_TECNICO_CANONICO = "12774333107"
_REGISTRO_VALIDACAO = "12566356804"


def _run(rows: list[MondaySourceRow]):
    return classify_board_dispositions(
        rows=rows,
        rules=audiencias_disposition_rules(),
        source_snapshot_timestamp=_TS,
    )


def _snapshot_121() -> list[MondaySourceRow]:
    rows = [MondaySourceRow(mid) for mid in AUDIENCIAS_ADOPT_MAP]  # 8 ADOPT
    rows += [MondaySourceRow(f"nominal-{i:04d}") for i in range(109)]  # 109 CREATE
    rows += [
        MondaySourceRow(_TECNICO_DAIANE),
        MondaySourceRow(_TECNICO_PLACEHOLDER),
        MondaySourceRow(_TECNICO_CANONICO),
        MondaySourceRow(_REGISTRO_VALIDACAO),
    ]
    return rows


class TestDispositions:
    def test_adopt_does_not_create_item(self) -> None:
        r = _run([MondaySourceRow("11322933382")])
        rec = r.record_for("11322933382")
        assert rec is not None
        assert rec.disposition == "ADOPT"
        assert rec.creates_sunday_item is False
        assert rec.sunday_item_id == "7043"

    def test_absorb_does_not_create_and_points_to_canonical(self) -> None:
        r = _run([MondaySourceRow("11322933382"), MondaySourceRow(_TECNICO_DAIANE)])
        alias = r.record_for(_TECNICO_DAIANE)
        assert alias is not None
        assert alias.disposition == "ABSORB"
        assert alias.creates_sunday_item is False
        assert alias.canonical_monday_item_id == "11322933382"
        assert alias.sunday_item_id == "7043"

    def test_two_monday_ids_map_to_same_sunday_item(self) -> None:
        r = _run([MondaySourceRow("11322933382"), MondaySourceRow(_TECNICO_DAIANE)])
        assert set(r.monday_items_for_sunday("7043")) == {"11322933382", _TECNICO_DAIANE}
        assert r.canonical_monday_item_for_sunday("7043") == "11322933382"
        assert r.aliases_for_sunday("7043") == [_TECNICO_DAIANE]

    def test_placeholder_absorbed_into_canonical_time(self) -> None:
        r = _run([MondaySourceRow(_TECNICO_PLACEHOLDER), MondaySourceRow(_TECNICO_CANONICO)])
        canonical = r.record_for(_TECNICO_CANONICO)
        placeholder = r.record_for(_TECNICO_PLACEHOLDER)
        assert canonical is not None and canonical.disposition == "CREATE"
        assert placeholder is not None and placeholder.disposition == "ABSORB"
        assert placeholder.canonical_monday_item_id == _TECNICO_CANONICO
        assert placeholder.sunday_item_id is None  # canônico ainda não tem Sunday item

    def test_exclude_test_counted_without_creating(self) -> None:
        r = _run([MondaySourceRow(_REGISTRO_VALIDACAO)])
        rec = r.record_for(_REGISTRO_VALIDACAO)
        assert rec is not None
        assert rec.disposition == "EXCLUDE_TEST"
        assert rec.creates_sunday_item is False
        assert rec.disposition_reason == "VALIDATION_RECORD"
        assert r.accounting.counts["EXCLUDE_TEST"] == 1
        assert r.accounting.accounted == 1


class TestConservationAndNative:
    def test_sunday_native_not_in_denominator(self) -> None:
        r = _run(_snapshot_121())
        assert r.accounting.source_snapshot_total == 121
        assert len(r.natives) == 1
        assert r.natives[0].sunday_item_id == "7065"

    def test_source_rows_conservation_121(self) -> None:
        r = _run(_snapshot_121())
        c = r.accounting.counts
        assert c["ADOPT"] == 8
        assert c["ABSORB"] == 2
        assert c["EXCLUDE_TEST"] == 1
        assert c["CREATE"] == 110  # 109 nominais + 1 técnico canônico
        assert c["MANUAL"] == 0
        assert c["ERROR"] == 0
        assert r.accounting.accounted == 121
        assert r.accounting.is_conserved is True

    def test_nominais_vs_tecnicos_breakdown(self) -> None:
        r = _run(_snapshot_121())
        tec = {_TECNICO_DAIANE, _TECNICO_PLACEHOLDER, _TECNICO_CANONICO, _REGISTRO_VALIDACAO}
        nominais = [rec for rec in r.records if rec.monday_item_id not in tec]
        tecnicos = [rec for rec in r.records if rec.monday_item_id in tec]
        assert len(nominais) == 117
        assert len(tecnicos) == 4
        assert dict(Counter(rec.disposition for rec in nominais)) == {"CREATE": 109, "ADOPT": 8}
        assert dict(Counter(rec.disposition for rec in tecnicos)) == {
            "ABSORB": 2,
            "CREATE": 1,
            "EXCLUDE_TEST": 1,
        }

    def test_idempotent_adopt_and_absorb(self) -> None:
        rows = _snapshot_121()
        first = _run(rows)
        second = _run(rows)
        assert first.as_dict()["dispositions"] == second.as_dict()["dispositions"]
        assert first.monday_items_for_sunday("7043") == second.monday_items_for_sunday("7043")


class TestGenericRules:
    def test_no_match_defaults_to_create(self) -> None:
        rules = BoardDispositionRules(monday_board_id="b", sunday_board_id="s")
        r = classify_board_dispositions(
            rows=[MondaySourceRow("x1"), MondaySourceRow("x2")],
            rules=rules,
            source_snapshot_timestamp=_TS,
        )
        assert r.accounting.counts["CREATE"] == 2
        assert r.accounting.is_conserved is True

    def test_board_ids(self) -> None:
        assert AUDIENCIAS_MONDAY_BOARD_ID == "4443295406"
        assert audiencias_disposition_rules().sunday_board_id == "72"
