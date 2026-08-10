"""Testes do cliente REST do Sunday (com transporte mockado)."""

from unittest.mock import patch

import pytest

from classificacao_procons.sunday.client import SundayClient, SundayClientError

_ENV_VARS = ("SUNDAY_API_URL", "SUNDAY_API_TOKEN", "LEGAL_API_URL", "LEGAL_API_TOKEN")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _client() -> SundayClient:
    return SundayClient(api_url="https://sunday-api.example/", api_token="tok")


class TestFromEnv:
    def test_should_require_api_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUNDAY_API_TOKEN", "tok")
        with pytest.raises(SundayClientError, match="SUNDAY_API_URL"):
            SundayClient.from_env()

    def test_should_require_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUNDAY_API_URL", "https://sunday-api.example")
        with pytest.raises(SundayClientError, match="SUNDAY_API_TOKEN"):
            SundayClient.from_env()

    def test_should_build_from_env_and_strip_trailing_slash(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SUNDAY_API_URL", "https://sunday-api.example/")
        monkeypatch.setenv("SUNDAY_API_TOKEN", "tok")
        client = SundayClient.from_env()
        assert client.api_url == "https://sunday-api.example"
        assert client.api_token == "tok"

    def test_should_accept_generic_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LEGAL_API_URL", "https://generic.example")
        monkeypatch.setenv("LEGAL_API_TOKEN", "gtok")
        client = SundayClient.from_env()
        assert client.api_url == "https://generic.example"
        assert client.api_token == "gtok"


class TestReadEndpoints:
    @patch.object(SundayClient, "_request")
    def test_should_list_workspaces(self, request_mock) -> None:
        request_mock.return_value = [
            {"id": "22", "name": "Support", "board_count": 6},
        ]
        workspaces = _client().list_workspaces()
        assert workspaces[0].id == "22"
        request_mock.assert_called_once_with("GET", "/workspaces")

    @patch.object(SundayClient, "_request")
    def test_should_list_boards_for_workspace(self, request_mock) -> None:
        request_mock.return_value = [{"id": "78", "name": "Legal - Acessos"}]
        boards = _client().list_boards(workspace_id="22")
        assert boards[0].id == "78"
        request_mock.assert_called_once_with("GET", "/boards?workspace_id=22")

    @patch.object(SundayClient, "_request")
    def test_should_list_boards_without_filter(self, request_mock) -> None:
        request_mock.return_value = []
        _client().list_boards()
        request_mock.assert_called_once_with("GET", "/boards")

    @patch.object(SundayClient, "_request")
    def test_should_list_columns(self, request_mock) -> None:
        request_mock.return_value = [
            {"id": "1", "key": "name", "type": "text", "label": "Nome"},
        ]
        columns = _client().list_columns("78")
        assert columns[0].key == "name"
        request_mock.assert_called_once_with("GET", "/boards/78/columns")

    @patch.object(SundayClient, "_request")
    def test_should_raise_when_list_endpoint_returns_object(self, request_mock) -> None:
        request_mock.return_value = {"unexpected": "object"}
        with pytest.raises(SundayClientError, match="Esperava lista"):
            _client().list_items("78")

    @patch.object(SundayClient, "_request")
    def test_should_get_board_detail(self, request_mock) -> None:
        request_mock.return_value = {"id": "79", "name": "Legal - Seguros", "status": "active"}
        board = _client().get_board("79")
        assert board.name == "Legal - Seguros"
        request_mock.assert_called_once_with("GET", "/boards/79")
