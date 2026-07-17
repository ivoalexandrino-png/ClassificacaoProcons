"""Testes do cadastro/atualização de processos judiciais no Monday.com."""

from datetime import date
from unittest.mock import patch

from classificacao_procons.litigio.models import EventoProcesso, ProvidenciaTipo
from classificacao_procons.litigio.monday_litigio import register_or_update_processo

ACCOUNT_RESPONSE = {"me": {"account": {"slug": "b4a"}}}

BOARD_RESPONSE = {
    "boards": [
        {
            "id": "222",
            "name": "processos judiciais",
            "groups": [{"id": "grp_acomp", "title": "acompanhamento"}],
            "columns": [
                {"id": "text_processo", "title": "Número do processo", "type": "text"},
                {"id": "text_tribunal", "title": "Tribunal", "type": "text"},
                {"id": "status_providencia", "title": "Providência", "type": "status"},
                {"id": "date_prazo", "title": "Prazo", "type": "date"},
                {"id": "date_audiencia", "title": "Data Audiência", "type": "date"},
                {"id": "link_certidao", "title": "Link Certidão", "type": "link"},
            ],
        },
    ],
}

CREATE_ITEM_RESPONSE = {"create_item": {"id": "555"}}
UPDATE_ITEM_RESPONSE = {"change_multiple_column_values": {"id": "555"}}


def _evento(**overrides: object) -> EventoProcesso:
    defaults: dict[str, object] = {
        "numero_processo": "00000012320268260100",
        "numero_processo_formatado": "0000001-23.2026.8.26.0100",
        "tribunal": "TJSP",
        "tipo_providencia": ProvidenciaTipo.MANIFESTACAO,
        "descricao": "Despacho: manifestação necessária.",
        "requer_atencao": True,
        "intimacao_id": 1,
        "data_disponibilizacao": date(2026, 7, 11),
        "prazo_data": date(2026, 7, 26),
        "data_audiencia": None,
        "certidao_url": "https://comunicaapi.pje.jus.br/api/v1/comunicacao/hash-1/certidao",
        "link_tribunal": "https://tjsp.jus.br/doc/1",
    }
    defaults.update(overrides)
    return EventoProcesso(**defaults)  # type: ignore[arg-type]


class TestRegisterOrUpdateProcesso:
    def test_should_return_none_when_token_missing(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            resultado = register_or_update_processo(_evento(), api_token=None)
        assert resultado is None

    @patch("classificacao_procons.monday.client._graphql_request")
    def test_should_create_item_when_processo_not_found(self, graphql_mock) -> None:
        graphql_mock.side_effect = [
            ACCOUNT_RESPONSE,
            BOARD_RESPONSE,
            {"items_page_by_column_values": {"items": []}},
            CREATE_ITEM_RESPONSE,
            *([UPDATE_ITEM_RESPONSE] * 5),
        ]

        resultado = register_or_update_processo(_evento(), api_token="token-test")

        assert resultado is not None
        assert resultado.criado is True
        assert resultado.item_id == "555"
        assert resultado.item_url == "https://b4a.monday.com/boards/222/pulses/555"

        create_call = graphql_mock.call_args_list[3]
        assert create_call.kwargs["variables"]["itemName"] == "0000001-23.2026.8.26.0100"

    @patch("classificacao_procons.monday.client._graphql_request")
    def test_should_update_existing_item_instead_of_creating_duplicate(
        self,
        graphql_mock,
    ) -> None:
        graphql_mock.side_effect = [
            ACCOUNT_RESPONSE,
            BOARD_RESPONSE,
            {"items_page_by_column_values": {"items": [{"id": "777"}]}},
            *([UPDATE_ITEM_RESPONSE] * 5),
        ]

        resultado = register_or_update_processo(_evento(), api_token="token-test")

        assert resultado is not None
        assert resultado.criado is False
        assert resultado.item_id == "777"
        # nenhuma chamada de create_item deve ocorrer na atualização
        queries = [call.kwargs["query"] for call in graphql_mock.call_args_list]
        assert all("create_item" not in query for query in queries)
