"""Testes do registro de providências no Monday."""

from unittest.mock import patch

import pytest

from classificacao_procons.juridico.models import ProcessoJudicial, Providencia
from classificacao_procons.juridico.monday_juridico import (
    _pick_juridico_board,
    register_providencia,
)
from classificacao_procons.monday.client import MondayBoardContext, MondayClientError
from classificacao_procons.monday.mapping import MondayColumn


def _providencia() -> Providencia:
    return Providencia(
        process_number="1023456-78.2026.8.26.0100",
        tipo="Contestar",
        descricao="Contestar — TJSP",
    )


def _processo() -> ProcessoJudicial:
    return ProcessoJudicial(process_number="1023456-78.2026.8.26.0100", tribunal="TJSP")


def _context() -> MondayBoardContext:
    columns = [MondayColumn(id="c_proc", title="Processo", column_type="text")]
    return MondayBoardContext(
        board_id="board-1",
        group_id="group-1",
        columns=columns,
        column_details=[],
        account_slug="b4a",
    )


class TestPickBoard:
    def test_should_prefer_exact_name(self) -> None:
        boards = [{"name": "Outro"}, {"name": "Jurídico"}]
        assert _pick_juridico_board(boards, "jurídico")["name"] == "Jurídico"

    def test_should_fallback_to_keyword(self) -> None:
        boards = [{"name": "Controle de Processos"}]
        assert _pick_juridico_board(boards, "inexistente")["name"] == "Controle de Processos"

    def test_should_return_none_when_no_match(self) -> None:
        assert _pick_juridico_board([{"name": "Contratos"}], "inexistente") is None


class TestRegisterProvidencia:
    def test_should_skip_without_token(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert register_providencia(_providencia(), _processo()) is None

    def test_should_raise_without_process_number(self) -> None:
        prov = Providencia(process_number="", tipo="Contestar", descricao="x")
        with pytest.raises(MondayClientError):
            register_providencia(prov, _processo(), api_token="t")

    @patch("classificacao_procons.juridico.monday_juridico._apply_complaint_column_values")
    @patch("classificacao_procons.juridico.monday_juridico._create_item", return_value="item-9")
    @patch(
        "classificacao_procons.juridico.monday_juridico._find_existing_item_id",
        return_value=None,
    )
    @patch("classificacao_procons.juridico.monday_juridico._load_board_context")
    def test_should_create_item(
        self,
        load_ctx_mock,
        _find_mock,
        create_mock,
        _apply_mock,
    ) -> None:
        load_ctx_mock.return_value = _context()
        result = register_providencia(_providencia(), _processo(), api_token="t")
        assert result is not None
        assert result.item_id == "item-9"
        assert result.item_url == "https://b4a.monday.com/boards/board-1/pulses/item-9"
        create_mock.assert_called_once()

    @patch(
        "classificacao_procons.juridico.monday_juridico._find_existing_item_id",
        return_value="existing-1",
    )
    @patch("classificacao_procons.juridico.monday_juridico._load_board_context")
    def test_should_skip_duplicate(self, load_ctx_mock, _find_mock) -> None:
        load_ctx_mock.return_value = _context()
        result = register_providencia(_providencia(), _processo(), api_token="t")
        assert result is not None
        assert result.skipped_duplicate is True
        assert result.item_id == "existing-1"
