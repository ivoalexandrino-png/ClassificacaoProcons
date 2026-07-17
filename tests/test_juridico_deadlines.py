"""Testes do cálculo de prazos processuais em dias úteis."""

from datetime import date

import pytest

from classificacao_procons.juridico.deadlines import (
    add_business_days,
    calculate_prazo_final,
    is_business_day,
    next_business_day,
)


class TestIsBusinessDay:
    def test_should_reject_saturday_and_sunday(self) -> None:
        assert not is_business_day(date(2026, 7, 18), frozenset())  # sábado
        assert not is_business_day(date(2026, 7, 19), frozenset())  # domingo

    def test_should_accept_weekday(self) -> None:
        assert is_business_day(date(2026, 7, 17), frozenset())  # sexta

    def test_should_reject_holiday(self) -> None:
        holiday = date(2026, 7, 17)
        assert not is_business_day(holiday, frozenset({holiday}))


class TestNextBusinessDay:
    def test_should_skip_weekend(self) -> None:
        # sexta 17/07 -> segunda 20/07
        assert next_business_day(date(2026, 7, 17), frozenset()) == date(2026, 7, 20)

    def test_should_skip_holiday(self) -> None:
        holidays = frozenset({date(2026, 7, 20)})
        assert next_business_day(date(2026, 7, 17), holidays) == date(2026, 7, 21)


class TestAddBusinessDays:
    def test_should_add_one_business_day_across_weekend(self) -> None:
        assert add_business_days(date(2026, 7, 17), 1, frozenset()) == date(2026, 7, 20)

    def test_should_add_multiple_business_days(self) -> None:
        assert add_business_days(date(2026, 7, 17), 5, frozenset()) == date(2026, 7, 24)

    def test_should_raise_for_non_positive(self) -> None:
        with pytest.raises(ValueError):
            add_business_days(date(2026, 7, 17), 0, frozenset())


class TestCalculatePrazoFinal:
    def test_should_count_business_days_from_publication(self) -> None:
        # publicação sexta 17/07, 15 dias úteis -> 07/08/2026
        result = calculate_prazo_final(publication_date=date(2026, 7, 17), dias=15)
        assert result == date(2026, 8, 7)

    def test_should_respect_holidays(self) -> None:
        holidays = [date(2026, 7, 20)]
        without = calculate_prazo_final(publication_date=date(2026, 7, 17), dias=5)
        with_holiday = calculate_prazo_final(
            publication_date=date(2026, 7, 17),
            dias=5,
            holidays=holidays,
        )
        assert with_holiday > without

    def test_should_support_corridos(self) -> None:
        # publicação quarta 15/07, 10 dias corridos -> vence 25/07 (sáb) -> prorroga 27/07
        result = calculate_prazo_final(
            publication_date=date(2026, 7, 15),
            dias=10,
            business_days=False,
        )
        assert result == date(2026, 7, 27)

    def test_should_raise_for_non_positive_days(self) -> None:
        with pytest.raises(ValueError):
            calculate_prazo_final(publication_date=date(2026, 7, 17), dias=0)
