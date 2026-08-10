"""Testes de parsing dos payloads REST do Sunday (offline).

Payloads baseados nas respostas reais observadas no discovery de 2026-08-10.
"""

from classificacao_procons.sunday.parser import (
    parse_board,
    parse_boards,
    parse_column,
    parse_columns,
    parse_group,
    parse_item,
    parse_workspace,
    parse_workspaces,
)

WORKSPACE_PAYLOAD = {
    "id": "22",
    "name": "Support - Finance, Legal, People",
    "slug": "support",
    "description": None,
    "business_unit": "shared",
    "archived": False,
    "board_count": 6,
    "member_count": 5,
    "created_at": "2026-08-10T00:00:00.000Z",
}

BOARD_PAYLOAD = {
    "id": "79",
    "name": "Legal - Seguros",
    "description": None,
    "status": "active",
    "template_key": "board",
    "status_set": [
        {"key": "to_do", "color": "amber", "label": "A fazer", "terminal": False},
        {"key": "follow_up", "color": "sky", "label": "Follow-up", "terminal": False},
        {"key": "done", "color": "emerald", "label": "Feito", "terminal": True},
    ],
}

COLUMN_PAYLOAD = {
    "id": "438",
    "board_id": "79",
    "key": "name",
    "type": "text",
    "label": "Nome",
    "position": 0,
    "is_system": True,
    "settings": {},
}

GROUP_PAYLOAD = {
    "id": "229",
    "board_id": "79",
    "name": "Itens",
    "color": "neutral",
    "position": 1,
}


class TestParseWorkspace:
    def test_should_map_core_fields(self) -> None:
        ws = parse_workspace(WORKSPACE_PAYLOAD)
        assert ws.id == "22"
        assert ws.name == "Support - Finance, Legal, People"
        assert ws.slug == "support"
        assert ws.business_unit == "shared"
        assert ws.board_count == 6
        assert ws.member_count == 5
        assert ws.archived is False

    def test_should_tolerate_missing_fields(self) -> None:
        ws = parse_workspace({"id": 5, "name": "X"})
        assert ws.id == "5"
        assert ws.slug is None
        assert ws.board_count is None


class TestParseBoard:
    def test_should_map_status_set(self) -> None:
        board = parse_board(BOARD_PAYLOAD)
        assert board.id == "79"
        assert board.name == "Legal - Seguros"
        assert board.status == "active"
        assert board.template_key == "board"
        assert len(board.status_set) == 3
        done = board.status_set[2]
        assert done.key == "done"
        assert done.label == "Feito"
        assert done.terminal is True

    def test_should_default_empty_status_set(self) -> None:
        board = parse_board({"id": "1", "name": "B"})
        assert board.status_set == ()

    def test_should_parse_board_list(self) -> None:
        boards = parse_boards([BOARD_PAYLOAD, {"id": "78", "name": "Legal - Acessos"}])
        assert [b.id for b in boards] == ["79", "78"]


class TestParseColumn:
    def test_should_map_key_type_label(self) -> None:
        column = parse_column(COLUMN_PAYLOAD)
        assert column.id == "438"
        assert column.key == "name"
        assert column.type == "text"
        assert column.label == "Nome"
        assert column.is_system is True
        assert column.settings == {}

    def test_should_default_settings_to_dict(self) -> None:
        column = parse_column({"id": "1", "key": "area", "type": "dropdown", "label": "Área"})
        assert column.settings == {}

    def test_should_parse_acessos_columns(self) -> None:
        payload = [
            {"id": "1", "key": "name", "type": "text", "label": "Nome"},
            {"id": "2", "key": "status", "type": "status", "label": "Status"},
            {"id": "3", "key": "owner", "type": "people", "label": "Responsável"},
            {"id": "4", "key": "target_date", "type": "date", "label": "Data"},
            {"id": "5", "key": "area", "type": "dropdown", "label": "Área"},
        ]
        columns = parse_columns(payload)
        assert [c.type for c in columns] == ["text", "status", "people", "date", "dropdown"]


class TestParseGroupAndItem:
    def test_should_map_group(self) -> None:
        group = parse_group(GROUP_PAYLOAD)
        assert group.id == "229"
        assert group.name == "Itens"
        assert group.board_id == "79"
        assert group.position == 1

    def test_should_map_item_name_top_level(self) -> None:
        item = parse_item({"id": "10", "name": "Fornecedor X", "group_id": "229"})
        assert item.id == "10"
        assert item.name == "Fornecedor X"
        assert item.group_id == "229"
        assert item.raw["name"] == "Fornecedor X"

    def test_should_map_item_name_from_values(self) -> None:
        item = parse_item({"id": "11", "values": {"name": "Fornecedor Y"}})
        assert item.name == "Fornecedor Y"

    def test_should_parse_workspace_list(self) -> None:
        workspaces = parse_workspaces([WORKSPACE_PAYLOAD])
        assert workspaces[0].id == "22"
