"""Testes de busca de board no Monday."""

from classificacao_procons.monday.client import _pick_board_by_name


class TestMondayBoardLookup:
    def test_should_find_board_by_exact_name(self) -> None:
        boards = [{"id": "1", "name": "procons"}, {"id": "2", "name": "outro"}]
        found = _pick_board_by_name(boards, "procons")
        assert found is not None
        assert found["id"] == "1"

    def test_should_find_board_by_fuzzy_procon_match(self) -> None:
        boards = [{"id": "9", "name": "Gestão Procon SP"}]
        found = _pick_board_by_name(boards, "procons")
        assert found is not None
        assert found["id"] == "9"
