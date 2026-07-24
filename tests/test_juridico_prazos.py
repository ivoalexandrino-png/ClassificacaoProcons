"""Testes da contagem de prazos em dias úteis."""

from datetime import date

import pytest

from classificacao_procons.juridico.prazos import (
    add_business_days,
    add_calendar_days,
    compute_due_date,
    is_business_day,
    next_business_day,
    subtract_business_days,
)


class TestIsBusinessDay:
    def test_should_return_true_on_weekday(self) -> None:
        assert is_business_day(date(2026, 7, 17))  # sexta-feira

    def test_should_return_false_on_weekend(self) -> None:
        assert not is_business_day(date(2026, 7, 18))  # sábado
        assert not is_business_day(date(2026, 7, 19))  # domingo


class TestNextBusinessDay:
    def test_should_keep_date_when_already_business_day(self) -> None:
        assert next_business_day(date(2026, 7, 17)) == date(2026, 7, 17)

    def test_should_move_to_monday_when_weekend(self) -> None:
        assert next_business_day(date(2026, 7, 18)) == date(2026, 7, 20)


class TestAddBusinessDays:
    def test_should_count_fifteen_business_days_excluding_start(self) -> None:
        # sexta 17/07 + 15 dias úteis → sexta 07/08
        assert add_business_days(date(2026, 7, 17), 15) == date(2026, 8, 7)

    def test_should_count_five_business_days_over_weekend(self) -> None:
        # quinta 16/07 + 5 dias úteis → quinta 23/07
        assert add_business_days(date(2026, 7, 16), 5) == date(2026, 7, 23)

    def test_should_return_same_day_when_zero_days_on_business_day(self) -> None:
        assert add_business_days(date(2026, 7, 17), 0) == date(2026, 7, 17)

    def test_should_raise_when_days_negative(self) -> None:
        with pytest.raises(ValueError, match="não pode ser negativo"):
            add_business_days(date(2026, 7, 17), -1)


class TestSubtractBusinessDays:
    def test_should_subtract_two_business_days_within_week(self) -> None:
        # sexta 07/08 - 2 dias úteis → quarta 05/08
        assert subtract_business_days(date(2026, 8, 7), 2) == date(2026, 8, 5)

    def test_should_skip_weekend_when_subtracting(self) -> None:
        # segunda 20/07 - 2 dias úteis → quinta 16/07 (pula sáb/dom)
        assert subtract_business_days(date(2026, 7, 20), 2) == date(2026, 7, 16)

    def test_should_return_same_day_when_zero_days(self) -> None:
        assert subtract_business_days(date(2026, 8, 7), 0) == date(2026, 8, 7)

    def test_should_raise_when_days_negative(self) -> None:
        with pytest.raises(ValueError, match="não pode ser negativo"):
            subtract_business_days(date(2026, 8, 7), -1)


class TestAddCalendarDays:
    def test_should_extend_to_next_business_day_when_ending_on_weekend(self) -> None:
        # sexta 17/07 + 15 corridos = sábado 01/08 → segunda 03/08
        assert add_calendar_days(date(2026, 7, 17), 15) == date(2026, 8, 3)

    def test_should_raise_when_days_negative(self) -> None:
        with pytest.raises(ValueError, match="não pode ser negativo"):
            add_calendar_days(date(2026, 7, 17), -5)


class TestComputeDueDate:
    def test_should_prefer_explicit_date_over_day_count(self) -> None:
        result = compute_due_date(
            base_date=date(2026, 7, 17),
            deadline_days=15,
            explicit_date=date(2026, 8, 20),
        )
        assert result == date(2026, 8, 20)

    def test_should_use_business_days_by_default(self) -> None:
        result = compute_due_date(base_date=date(2026, 7, 17), deadline_days=15)
        assert result == date(2026, 8, 7)

    def test_should_use_calendar_days_when_flagged(self) -> None:
        result = compute_due_date(
            base_date=date(2026, 7, 17),
            deadline_days=15,
            in_business_days=False,
        )
        assert result == date(2026, 8, 3)

    def test_should_return_none_when_no_deadline(self) -> None:
        assert compute_due_date(base_date=date(2026, 7, 17), deadline_days=None) is None
