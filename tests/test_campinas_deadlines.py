"""Testes dos prazos internos Campinas."""

from datetime import date

from classificacao_procons.campinas.deadlines import calculate_campinas_deadlines


class TestCampinasDeadlines:
    def test_should_calculate_sac_and_legal_deadlines(self) -> None:
        sac, legal = calculate_campinas_deadlines(base_date=date(2026, 7, 10))
        assert sac == date(2026, 7, 13)
        assert legal == date(2026, 7, 14)
