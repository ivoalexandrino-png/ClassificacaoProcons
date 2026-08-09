"""Testes do núcleo de análise do radar (relevância + status + dedup)."""

from datetime import datetime

from classificacao_procons.radar.analise import (
    analyze_snapshot,
    dedup_key_for,
    relevant_areas,
)
from classificacao_procons.radar.models import CORE_AREAS, Edital, RadarSnapshot


def _edital(**kwargs) -> Edital:
    base = {
        "source_key": "cnpq",
        "source_name": "CNPq",
        "title": "Edital de pesquisa em Direito",
        "url": "https://cnpq.br/edital-1",
        "status": "aberto",
    }
    base.update(kwargs)
    return Edital(**base)


def _snapshot(*editais: Edital) -> RadarSnapshot:
    return RadarSnapshot(captured_at=datetime(2026, 8, 9, 9, 0), editais=tuple(editais))


class TestRelevantAreas:
    def test_should_use_edital_areas(self) -> None:
        edital = _edital(areas=("saude",), title="Chamada X")
        assert relevant_areas(edital, CORE_AREAS) == ("saude",)

    def test_should_detect_from_text_when_areas_missing(self) -> None:
        edital = _edital(areas=(), title="Bolsa em educação básica")
        assert relevant_areas(edital, CORE_AREAS) == ("educacao",)

    def test_should_respect_interest_filter(self) -> None:
        edital = _edital(areas=("saude", "direito"))
        assert relevant_areas(edital, ("saude",)) == ("saude",)


class TestDedupKey:
    def test_should_prefer_raw_id(self) -> None:
        edital = _edital(raw_id="ABC-123")
        assert dedup_key_for(edital) == "cnpq:ABC-123"

    def test_should_fall_back_to_url(self) -> None:
        edital = _edital(raw_id=None, url="https://cnpq.br/x")
        assert dedup_key_for(edital) == "cnpq:https://cnpq.br/x"

    def test_should_fall_back_to_title_slug(self) -> None:
        edital = _edital(raw_id=None, url="", title="Edital de Direito")
        assert dedup_key_for(edital) == "cnpq:edital-de-direito"


class TestAnalyzeSnapshot:
    def test_should_keep_relevant_open_editais(self) -> None:
        snapshot = _snapshot(
            _edital(title="Edital em Direito", areas=("direito",)),
            _edital(title="Edital de aeronáutica", areas=(), url="https://x/aero"),
        )
        analysis = analyze_snapshot(snapshot)
        assert len(analysis.matches) == 1
        assert analysis.matches[0].matched_areas == ("direito",)

    def test_should_exclude_closed_by_default(self) -> None:
        snapshot = _snapshot(_edital(status="encerrado"))
        assert analyze_snapshot(snapshot).matches == ()

    def test_should_include_closed_when_requested(self) -> None:
        snapshot = _snapshot(_edital(status="encerrado"))
        analysis = analyze_snapshot(snapshot, include_closed=True)
        assert len(analysis.matches) == 1

    def test_should_filter_by_interest_area(self) -> None:
        snapshot = _snapshot(
            _edital(title="Saúde pública", areas=("saude",), url="https://x/s"),
            _edital(title="Direito penal", areas=("direito",), url="https://x/d"),
        )
        analysis = analyze_snapshot(snapshot, interest_areas=("saude",))
        assert len(analysis.matches) == 1
        assert analysis.matches[0].edital.title == "Saúde pública"

    def test_should_sort_open_before_upcoming(self) -> None:
        snapshot = _snapshot(
            _edital(title="Previsto", areas=("direito",), status="previsto", url="https://x/p"),
            _edital(title="Aberto", areas=("direito",), status="aberto", url="https://x/a"),
        )
        analysis = analyze_snapshot(snapshot)
        assert analysis.matches[0].status == "aberto"
        assert analysis.open_matches and analysis.open_matches[0].edital.title == "Aberto"

    def test_should_report_no_matches_when_irrelevant(self) -> None:
        snapshot = _snapshot(_edital(title="Física quântica", areas=(), url="https://x/f"))
        analysis = analyze_snapshot(snapshot)
        assert not analysis.has_matches
