"""Testes do cliente DataJud (com mocks de rede)."""

import io
import json
import urllib.error
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from classificacao_procons.juridico.datajud import (
    DataJudError,
    fetch_case_movements,
    get_api_key_from_env,
)

PROCESS_NUMBER = "1001234-83.2026.8.26.0100"


@pytest.fixture(autouse=True)
def _no_throttle():
    """Desliga o espaçamento entre chamadas para os testes não dormirem."""
    with patch("classificacao_procons.juridico.datajud._throttle"):
        yield


def _datajud_response(movements: list[dict]) -> dict:
    return {
        "hits": {
            "hits": [
                {"_source": {"numeroProcesso": "10012348320268260100", "movimentos": movements}},
            ],
        },
    }


def _mock_urlopen(payload: dict) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response
    return MagicMock(return_value=response)


class TestFetchCaseMovements:
    def test_should_return_movements_sorted_by_most_recent(self) -> None:
        payload = _datajud_response(
            [
                {"codigo": 26, "nome": "Distribuição", "dataHora": "2026-01-10T09:00:00.000Z"},
                {"codigo": 51, "nome": "Audiência", "dataHora": "2026-07-01T14:00:00.000Z"},
            ],
        )
        with patch("urllib.request.urlopen", _mock_urlopen(payload)) as urlopen:
            movements = fetch_case_movements(PROCESS_NUMBER, api_key="chave-teste")

        assert [item.movement_name for item in movements] == ["Audiência", "Distribuição"]
        assert movements[0].movement_code == 51
        assert movements[0].movement_datetime is not None
        assert movements[0].movement_datetime.year == 2026

        request = urlopen.call_args.args[0]
        assert "api_publica_tjsp" in request.full_url
        assert request.headers["Authorization"] == "APIKey chave-teste"

    def test_should_limit_number_of_movements(self) -> None:
        payload = _datajud_response(
            [
                {"nome": f"Movimento {index}", "dataHora": f"2026-01-{index:02d}T00:00:00Z"}
                for index in range(1, 11)
            ],
        )
        with patch("urllib.request.urlopen", _mock_urlopen(payload)):
            movements = fetch_case_movements(PROCESS_NUMBER, api_key="chave", limit=3)
        assert len(movements) == 3

    def test_should_return_empty_list_when_process_not_found(self) -> None:
        with patch("urllib.request.urlopen", _mock_urlopen({"hits": {"hits": []}})):
            assert fetch_case_movements(PROCESS_NUMBER, api_key="chave") == []

    def test_should_ignore_movements_without_name(self) -> None:
        payload = _datajud_response([{"codigo": 1}, {"nome": "Conclusão"}])
        with patch("urllib.request.urlopen", _mock_urlopen(payload)):
            movements = fetch_case_movements(PROCESS_NUMBER, api_key="chave")
        assert [item.movement_name for item in movements] == ["Conclusão"]
        assert movements[0].movement_datetime is None

    def test_should_raise_when_api_key_is_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATAJUD_API_KEY", raising=False)
        with pytest.raises(DataJudError, match="DATAJUD_API_KEY"):
            fetch_case_movements(PROCESS_NUMBER)

    def test_should_strip_apikey_prefix_from_explicit_key(self) -> None:
        payload = _datajud_response([])
        with patch("urllib.request.urlopen", _mock_urlopen(payload)) as urlopen:
            fetch_case_movements(PROCESS_NUMBER, api_key="APIKey chave-teste")
        request = urlopen.call_args.args[0]
        assert request.headers["Authorization"] == "APIKey chave-teste"

    def test_should_raise_when_tribunal_is_not_supported(self) -> None:
        with pytest.raises(DataJudError, match="Tribunal não suportado"):
            fetch_case_movements("1001234-03.2026.1.00.0000", api_key="chave")

    def test_should_use_explicit_alias_when_provided(self) -> None:
        payload = _datajud_response([])
        with patch("urllib.request.urlopen", _mock_urlopen(payload)) as urlopen:
            fetch_case_movements("1001234-03.2026.1.00.0000", api_key="chave", alias="stf")
        request = urlopen.call_args.args[0]
        assert "api_publica_stf" in request.full_url

    def test_should_wrap_read_timeout_as_datajud_error(self) -> None:
        """Timeout no meio da leitura (TimeoutError) não pode derrubar o batch."""
        with (
            patch("urllib.request.urlopen", MagicMock(side_effect=TimeoutError("read timed out"))),
            patch("classificacao_procons.juridico.datajud.time.sleep"),
            pytest.raises(DataJudError, match="DataJud indisponível"),
        ):
            fetch_case_movements(PROCESS_NUMBER, api_key="chave")

    def test_should_retry_on_http_429_and_succeed(self) -> None:
        """Rate limit do DataJud (429) é retentado com backoff."""
        payload = _datajud_response([{"nome": "Conclusão"}])
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        error_429 = urllib.error.HTTPError(
            url="https://api-publica.datajud.cnj.jus.br",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b"rejected"),
        )
        urlopen = MagicMock(side_effect=[error_429, response])
        with (
            patch("urllib.request.urlopen", urlopen),
            patch("classificacao_procons.juridico.datajud.time.sleep") as sleep,
        ):
            movements = fetch_case_movements(PROCESS_NUMBER, api_key="chave")

        assert [item.movement_name for item in movements] == ["Conclusão"]
        assert urlopen.call_count == 2
        sleep.assert_called_once()

    def test_should_not_retry_on_http_401(self) -> None:
        error_401 = urllib.error.HTTPError(
            url="https://api-publica.datajud.cnj.jus.br",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b"unauthorized"),
        )
        urlopen = MagicMock(side_effect=error_401)
        with (
            patch("urllib.request.urlopen", urlopen),
            patch("classificacao_procons.juridico.datajud.time.sleep") as sleep,
            pytest.raises(DataJudError, match="HTTP 401"),
        ):
            fetch_case_movements(PROCESS_NUMBER, api_key="chave")
        assert urlopen.call_count == 1
        sleep.assert_not_called()

    def test_should_raise_on_http_error(self) -> None:
        error = urllib.error.HTTPError(
            url="https://api-publica.datajud.cnj.jus.br",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b"chave invalida"),
        )
        with (
            patch("urllib.request.urlopen", MagicMock(side_effect=error)),
            pytest.raises(DataJudError, match="HTTP 401"),
        ):
            fetch_case_movements(PROCESS_NUMBER, api_key="chave")

    def test_should_parse_naive_datetime_without_timezone(self) -> None:
        payload = _datajud_response([{"nome": "Juntada", "dataHora": "2026-05-06T00:00:00"}])
        with patch("urllib.request.urlopen", _mock_urlopen(payload)):
            movements = fetch_case_movements(PROCESS_NUMBER, api_key="chave")
        assert movements[0].movement_datetime == datetime(2026, 5, 6)


class TestGetApiKeyFromEnv:
    def test_should_return_none_when_env_is_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATAJUD_API_KEY", "   ")
        assert get_api_key_from_env() is None

    def test_should_return_key_as_is_when_no_prefix(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DATAJUD_API_KEY", " chave-teste ")
        assert get_api_key_from_env() == "chave-teste"

    @pytest.mark.parametrize(
        "raw",
        ["APIKey chave-teste", "ApiKey chave-teste", "apikey: chave-teste", "APIKey  chave-teste"],
    )
    def test_should_strip_apikey_prefix_when_present(
        self, raw: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DATAJUD_API_KEY", raw)
        assert get_api_key_from_env() == "chave-teste"

    def test_should_return_none_when_env_has_only_prefix(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DATAJUD_API_KEY", "APIKey ")
        assert get_api_key_from_env() is None
