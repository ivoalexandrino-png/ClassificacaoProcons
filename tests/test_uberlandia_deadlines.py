"""Testes dos prazos Uberlândia."""

from datetime import date

from classificacao_procons.uberlandia.deadlines import calculate_uberlandia_deadlines


class TestUberlandiaDeadlines:
    def test_should_calculate_sac_and_legal_deadlines(self) -> None:
        sac, legal = calculate_uberlandia_deadlines(base_date=date(2026, 7, 20))
        assert sac == date(2026, 7, 25)
        assert legal == date(2026, 7, 26)
