"""Testes dos prazos SC/SSP."""

from datetime import date

from classificacao_procons.sc.deadlines import calculate_sc_deadlines


class TestScDeadlines:
    def test_should_calculate_sac_legal_and_procon_deadlines(self) -> None:
        sac, legal, procon = calculate_sc_deadlines(
            base_date=date(2026, 6, 30),
            received_date=date(2026, 7, 20),
        )
        assert sac == date(2026, 7, 5)
        assert legal == date(2026, 7, 6)
        assert procon == date(2026, 8, 17)
