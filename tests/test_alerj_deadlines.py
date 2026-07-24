"""Testes dos prazos ALERJ."""

from datetime import date

from classificacao_procons.alerj.deadlines import calculate_alerj_deadlines


class TestAlerjDeadlines:
    def test_should_calculate_sac_legal_and_procon_deadlines(self) -> None:
        sac, legal, procon = calculate_alerj_deadlines(received_date=date(2026, 3, 16))
        assert sac == date(2026, 3, 21)
        assert legal == date(2026, 3, 22)
        assert procon == date(2026, 3, 26)
