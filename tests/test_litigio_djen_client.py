"""Testes do cliente da API do DJEN (Comunica PJe)."""

from datetime import date
from unittest.mock import patch

import pytest

from classificacao_procons.litigio.djen_client import (
    DjenClientError,
    DjenQueryOptions,
    consultar_intimacoes,
    parse_comunicacao_item,
)

RAW_ITEM = {
    "id": 661000001,
    "hash": "aBcDeFgHiJkLmNoPqRsTuVwXyZ01234",
    "numero_processo": "00000012320268260100",
    "numeroprocessocommascara": "0000001-23.2026.8.26.0100",
    "siglaTribunal": "TJSP",
    "tipoComunicacao": "Intimação",
    "tipoDocumento": "Despacho",
    "nomeOrgao": "1ª Vara Cível de São Paulo",
    "nomeClasse": "Procedimento Comum Cível",
    "data_disponibilizacao": "2026-07-11",
    "texto": "<p>Vistos. Intime-se a parte autora.</p>",
    "link": "https://tjsp.jus.br/doc/1",
    "status": "publicada",
    "motivo_cancelamento": None,
    "destinatarios": [{"nome": "FULANO DE TAL", "polo": "A"}],
    "destinatarioadvogados": [
        {"advogado": {"nome": "ADVOGADA EXEMPLO", "numero_oab": "123456", "uf_oab": "SP"}},
    ],
}


class TestParseComunicacaoItem:
    def test_should_parse_all_fields_when_item_is_complete(self) -> None:
        intimacao = parse_comunicacao_item(RAW_ITEM)

        assert intimacao is not None
        assert intimacao.id == 661000001
        assert intimacao.numero_processo == "00000012320268260100"
        assert intimacao.numero_processo_formatado == "0000001-23.2026.8.26.0100"
        assert intimacao.tribunal == "TJSP"
        assert intimacao.tipo_documento == "Despacho"
        assert intimacao.data_disponibilizacao == date(2026, 7, 11)
        assert intimacao.cancelada is False
        assert intimacao.certidao_url == (
            "https://comunicaapi.pje.jus.br/api/v1/comunicacao/"
            "aBcDeFgHiJkLmNoPqRsTuVwXyZ01234/certidao"
        )
        assert len(intimacao.advogados) == 1
        assert intimacao.advogados[0].numero_oab == "123456"

    def test_should_return_none_when_id_is_missing(self) -> None:
        raw = {**RAW_ITEM}
        del raw["id"]
        assert parse_comunicacao_item(raw) is None

    def test_should_return_none_when_numero_processo_is_empty(self) -> None:
        raw = {**RAW_ITEM, "numero_processo": ""}
        assert parse_comunicacao_item(raw) is None

    def test_should_return_none_when_data_disponibilizacao_is_missing(self) -> None:
        raw = {**RAW_ITEM}
        del raw["data_disponibilizacao"]
        assert parse_comunicacao_item(raw) is None

    def test_should_mark_cancelada_when_motivo_cancelamento_is_set(self) -> None:
        raw = {**RAW_ITEM, "motivo_cancelamento": "Erro de expedição"}
        intimacao = parse_comunicacao_item(raw)
        assert intimacao is not None
        assert intimacao.cancelada is True

    def test_should_sanitize_hostile_html_in_texto(self) -> None:
        raw = {
            **RAW_ITEM,
            "texto": '<div class="fixed inset-0 z-50" onclick="alert(1)">Oi</div>',
        }
        intimacao = parse_comunicacao_item(raw)
        assert intimacao is not None
        assert "class=" not in intimacao.texto
        assert "onclick" not in intimacao.texto
        assert "Oi" in intimacao.texto

    def test_should_ignore_advogado_without_numero_oab(self) -> None:
        raw = {
            **RAW_ITEM,
            "destinatarioadvogados": [{"advogado": {"nome": "SEM OAB", "numero_oab": ""}}],
        }
        intimacao = parse_comunicacao_item(raw)
        assert intimacao is not None
        assert intimacao.advogados == ()


def _default_options(**overrides: object) -> DjenQueryOptions:
    defaults: dict[str, object] = {
        "data_inicio": date(2026, 7, 10),
        "data_fim": date(2026, 7, 11),
        "numero_oab": "123456",
        "uf_oab": "SP",
    }
    defaults.update(overrides)
    return DjenQueryOptions(**defaults)  # type: ignore[arg-type]


class TestConsultarIntimacoes:
    @patch("classificacao_procons.litigio.djen_client.time.sleep")
    @patch("classificacao_procons.litigio.djen_client._http_get_json")
    def test_should_query_all_oab_suffix_variants(self, http_mock, _sleep_mock) -> None:
        http_mock.return_value = {"count": 0, "items": []}

        consultar_intimacoes(_default_options())

        assert http_mock.call_count == 7  # sete variantes de sufixo de OAB
        variantes = {call.args[0]["numeroOab"] for call in http_mock.call_args_list}
        assert variantes == {"123456", "123456-O", "123456-A", "123456-N", "123456-B",
                              "123456-S", "123456-E"}

    @patch("classificacao_procons.litigio.djen_client.time.sleep")
    @patch("classificacao_procons.litigio.djen_client._http_get_json")
    def test_should_query_once_when_numero_oab_is_absent(self, http_mock, _sleep_mock) -> None:
        http_mock.return_value = {"count": 0, "items": []}

        consultar_intimacoes(_default_options(numero_oab=None))

        assert http_mock.call_count == 1
        assert "numeroOab" not in http_mock.call_args_list[0].args[0]

    @patch("classificacao_procons.litigio.djen_client.time.sleep")
    @patch("classificacao_procons.litigio.djen_client._http_get_json")
    def test_should_deduplicate_by_id_across_variants(self, http_mock, _sleep_mock) -> None:
        http_mock.return_value = {"count": 1, "items": [RAW_ITEM]}

        resultado = consultar_intimacoes(_default_options())

        assert len(resultado) == 1
        assert resultado[0].id == RAW_ITEM["id"]

    @patch("classificacao_procons.litigio.djen_client.time.sleep")
    @patch("classificacao_procons.litigio.djen_client._http_get_json")
    def test_should_prefer_cancelled_version_over_original(self, http_mock, _sleep_mock) -> None:
        original = dict(RAW_ITEM)
        cancelada = {**RAW_ITEM, "motivo_cancelamento": "Erro de expedição"}
        # primeira variante devolve o original, a segunda a versão cancelada
        http_mock.side_effect = [
            {"count": 1, "items": [original]},
            {"count": 1, "items": [cancelada]},
        ] + [{"count": 0, "items": []}] * 10

        resultado = consultar_intimacoes(_default_options())

        assert len(resultado) == 1
        assert resultado[0].cancelada is True

    @patch("classificacao_procons.litigio.djen_client.time.sleep")
    @patch("classificacao_procons.litigio.djen_client._http_get_json")
    def test_should_sort_result_by_id(self, http_mock, _sleep_mock) -> None:
        item_a = {**RAW_ITEM, "id": 2}
        item_b = {**RAW_ITEM, "id": 1}
        http_mock.return_value = {"count": 2, "items": [item_a, item_b]}

        resultado = consultar_intimacoes(_default_options(numero_oab=None))

        assert [item.id for item in resultado] == [1, 2]

    @patch("classificacao_procons.litigio.djen_client.time.sleep")
    @patch("classificacao_procons.litigio.djen_client._http_get_json")
    def test_should_retry_transient_empty_page_before_giving_up(
        self,
        http_mock,
        _sleep_mock,
    ) -> None:
        http_mock.side_effect = [
            {"count": 2, "items": [RAW_ITEM]},
            {"count": 2, "items": []},
            {"count": 2, "items": [{**RAW_ITEM, "id": 2}]},
        ] + [{"count": 0, "items": []}] * 10

        resultado = consultar_intimacoes(_default_options(numero_oab=None))

        assert len(resultado) == 2

    @patch("classificacao_procons.litigio.djen_client._http_get_json")
    def test_should_raise_djen_client_error_when_http_layer_fails(self, http_mock) -> None:
        http_mock.side_effect = DjenClientError("DJEN respondeu HTTP 500.")

        with pytest.raises(DjenClientError):
            consultar_intimacoes(_default_options(numero_oab=None))


class TestHttpGetJson403:
    def test_should_raise_clear_error_on_geo_block(self) -> None:
        import urllib.error

        from classificacao_procons.litigio.djen_client import _http_get_json

        http_error = urllib.error.HTTPError(
            url="https://comunicaapi.pje.jus.br/api/v1/comunicacao",
            code=403,
            msg="Forbidden",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )
        with (
            patch(
                "classificacao_procons.litigio.djen_client.urllib.request.urlopen",
                side_effect=http_error,
            ),
            pytest.raises(DjenClientError, match="IPs brasileiros"),
        ):
            _http_get_json({"pagina": "1"})
