"""Testes de retentativa em erros transitórios do Monday."""

from classificacao_procons.monday.client import MondayClientError, _is_transient_monday_error


class TestTransientMondayErrors:
    def test_should_treat_item_lock_error_as_transient(self) -> None:
        error = MondayClientError("Failed to lock item id for graphql mutation")

        assert _is_transient_monday_error(error) is True

    def test_should_not_treat_validation_error_as_transient(self) -> None:
        error = MondayClientError("Column value invalid")

        assert _is_transient_monday_error(error) is False
