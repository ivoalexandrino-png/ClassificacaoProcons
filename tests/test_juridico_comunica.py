"""Testes do cliente Comunica/Domicílio Judicial Eletrônico (com mocks de rede)."""

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from classificacao_procons.juridico.comunica import ComunicaError, fetch_case_communications

PROCESS_NUMBER = "1001234-83.2026.8.26.0100"


def _mock_urlopen(payload: object) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response
    return MagicMock(return_value=response)


class TestFetchCaseCommunications:
    def test_should_parse_communications_with_teor(self) -> None:
        payload = {
            "count": 1,
            "items": [
                {
                    "texto": "CITAÇÃO da parte ré para contestar em 15 dias úteis.",
                    "tipoComunicacao": "Citação",
                    "siglaTribunal": "TJSP",
                    "nomeOrgao": "4ª Vara Cível de São Paulo",
                    "data_disponibilizacao": "2026-07-15",
                    "link": "https://comunica.pje.jus.br/consulta/123",
                },
            ],
        }
        with patch("urllib.request.urlopen", _mock_urlopen(payload)) as urlopen:
            communications = fetch_case_communications(PROCESS_NUMBER)

        assert len(communications) == 1
        communication = communications[0]
        assert "CITAÇÃO" in communication.text
        assert communication.communication_type == "Citação"
        assert communication.tribunal == "TJSP"
        assert communication.organ == "4ª Vara Cível de São Paulo"
        assert communication.available_date == "2026-07-15"

        request = urlopen.call_args.args[0]
        assert "numeroProcesso=10012348320268260100" in request.full_url

    def test_should_support_snake_case_keys(self) -> None:
        payload = {
            "items": [
                {
                    "teor": "Intimação para manifestação.",
                    "tipo_comunicacao": "Intimação",
                    "sigla_tribunal": "TRT2",
                },
            ],
        }
        with patch("urllib.request.urlopen", _mock_urlopen(payload)):
            communications = fetch_case_communications(PROCESS_NUMBER)
        assert communications[0].communication_type == "Intimação"
        assert communications[0].tribunal == "TRT2"

    def test_should_return_empty_list_when_no_items(self) -> None:
        with patch("urllib.request.urlopen", _mock_urlopen({"count": 0, "items": []})):
            assert fetch_case_communications(PROCESS_NUMBER) == []

    def test_should_ignore_items_without_text(self) -> None:
        payload = {"items": [{"tipoComunicacao": "Citação"}, {"texto": "Teor válido."}]}
        with patch("urllib.request.urlopen", _mock_urlopen(payload)):
            communications = fetch_case_communications(PROCESS_NUMBER)
        assert len(communications) == 1
        assert communications[0].text == "Teor válido."

    def test_should_respect_limit(self) -> None:
        payload = {"items": [{"texto": f"Teor {index}"} for index in range(10)]}
        with patch("urllib.request.urlopen", _mock_urlopen(payload)):
            communications = fetch_case_communications(PROCESS_NUMBER, limit=2)
        assert len(communications) == 2

    def test_should_raise_on_http_error(self) -> None:
        error = urllib.error.HTTPError(
            url="https://comunicaapi.pje.jus.br",
            code=500,
            msg="Server Error",
            hdrs=None,
            fp=io.BytesIO(b"erro interno"),
        )
        with (
            patch("urllib.request.urlopen", MagicMock(side_effect=error)),
            pytest.raises(ComunicaError, match="HTTP 500"),
        ):
            fetch_case_communications(PROCESS_NUMBER)

    def test_should_return_empty_when_payload_has_unexpected_shape(self) -> None:
        with patch("urllib.request.urlopen", _mock_urlopen({"items": "nada"})):
            assert fetch_case_communications(PROCESS_NUMBER) == []
