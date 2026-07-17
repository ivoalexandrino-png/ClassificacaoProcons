"""Testes do pipeline de monitoramento de litígio."""

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from classificacao_procons.litigio.djen_client import DjenClientError
from classificacao_procons.litigio.hooks import limpar_handlers, registrar_handler
from classificacao_procons.litigio.models import Intimacao
from classificacao_procons.litigio.monday_litigio import MondayLitigioResult
from classificacao_procons.litigio.pipeline import (
    LitigioPipelineError,
    LitigioPipelineOptions,
    monitorar_intimacoes,
)


def _intimacao(**overrides: object) -> Intimacao:
    defaults: dict[str, object] = {
        "id": 1,
        "hash": "hash-1",
        "numero_processo": "00000012320268260100",
        "numero_processo_formatado": "0000001-23.2026.8.26.0100",
        "tribunal": "TJSP",
        "tipo_comunicacao": "Intimação",
        "tipo_documento": "Despacho",
        "orgao": "1ª Vara Cível",
        "classe_processual": "Procedimento Comum",
        "data_disponibilizacao": date(2026, 7, 11),
        "texto": "Intime-se no prazo de 15 dias para manifestação.",
    }
    defaults.update(overrides)
    return Intimacao(**defaults)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_handlers():
    limpar_handlers()
    yield
    limpar_handlers()


def _options(tmp_path: Path, **overrides: object) -> LitigioPipelineOptions:
    defaults: dict[str, object] = {
        "numero_oab": "123456",
        "uf_oab": "SP",
        "data_inicio": date(2026, 7, 10),
        "data_fim": date(2026, 7, 11),
        "state_path": tmp_path / "processadas.json",
        "eventos_log_path": tmp_path / "eventos.jsonl",
        "register_on_monday": False,
    }
    defaults.update(overrides)
    return LitigioPipelineOptions(**defaults)  # type: ignore[arg-type]


class TestMonitorarIntimacoesValidacao:
    def test_should_raise_when_numero_oab_is_missing(self, tmp_path: Path) -> None:
        options = _options(tmp_path, numero_oab="")
        with pytest.raises(LitigioPipelineError, match="numero_oab"):
            monitorar_intimacoes(options)

    def test_should_raise_when_uf_oab_is_missing(self, tmp_path: Path) -> None:
        options = _options(tmp_path, uf_oab="")
        with pytest.raises(LitigioPipelineError, match="numero_oab"):
            monitorar_intimacoes(options)

    @patch("classificacao_procons.litigio.pipeline._consultar_djen")
    def test_should_wrap_djen_error_as_pipeline_error(self, djen_mock, tmp_path: Path) -> None:
        djen_mock.side_effect = DjenClientError("DJEN respondeu HTTP 500.")
        with pytest.raises(LitigioPipelineError, match="DJEN respondeu HTTP 500"):
            monitorar_intimacoes(_options(tmp_path))


class TestMonitorarIntimacoesFluxo:
    @patch("classificacao_procons.litigio.pipeline._consultar_djen")
    def test_should_return_empty_list_when_no_new_intimacoes(
        self,
        djen_mock,
        tmp_path: Path,
    ) -> None:
        djen_mock.return_value = []
        eventos = monitorar_intimacoes(_options(tmp_path))
        assert eventos == []

    @patch("classificacao_procons.litigio.pipeline._consultar_djen")
    def test_should_build_evento_with_prazo_for_new_intimacao(
        self,
        djen_mock,
        tmp_path: Path,
    ) -> None:
        djen_mock.return_value = [_intimacao()]

        eventos = monitorar_intimacoes(_options(tmp_path))

        assert len(eventos) == 1
        evento = eventos[0]
        assert evento.numero_processo == "00000012320268260100"
        assert evento.requer_atencao is True
        assert evento.prazo_data == date(2026, 7, 26)

    @patch("classificacao_procons.litigio.pipeline._consultar_djen")
    def test_should_skip_already_processed_intimacao_on_second_run(
        self,
        djen_mock,
        tmp_path: Path,
    ) -> None:
        djen_mock.return_value = [_intimacao()]
        options = _options(tmp_path)

        primeira_execucao = monitorar_intimacoes(options)
        segunda_execucao = monitorar_intimacoes(options)

        assert len(primeira_execucao) == 1
        assert segunda_execucao == []

    @patch("classificacao_procons.litigio.pipeline._consultar_djen")
    def test_should_not_persist_state_in_dry_run(self, djen_mock, tmp_path: Path) -> None:
        djen_mock.return_value = [_intimacao()]
        options = _options(tmp_path, dry_run=True)

        eventos = monitorar_intimacoes(options)

        assert len(eventos) == 1
        assert not options.state_path.exists()
        assert not options.eventos_log_path.exists()

    @patch("classificacao_procons.litigio.pipeline._consultar_djen")
    def test_should_append_evento_to_log_file(self, djen_mock, tmp_path: Path) -> None:
        djen_mock.return_value = [_intimacao()]
        options = _options(tmp_path)

        monitorar_intimacoes(options)

        assert options.eventos_log_path.exists()
        conteudo = options.eventos_log_path.read_text(encoding="utf-8").strip()
        assert "00000012320268260100" in conteudo

    @patch("classificacao_procons.litigio.pipeline._consultar_djen")
    def test_should_notify_registered_handlers(self, djen_mock, tmp_path: Path) -> None:
        djen_mock.return_value = [_intimacao()]
        eventos_recebidos = []
        registrar_handler(eventos_recebidos.append)

        monitorar_intimacoes(_options(tmp_path))

        assert len(eventos_recebidos) == 1
        assert eventos_recebidos[0].numero_processo == "00000012320268260100"

    @patch("classificacao_procons.litigio.pipeline._consultar_djen")
    def test_should_not_notify_handlers_in_dry_run(self, djen_mock, tmp_path: Path) -> None:
        djen_mock.return_value = [_intimacao()]
        eventos_recebidos = []
        registrar_handler(eventos_recebidos.append)

        monitorar_intimacoes(_options(tmp_path, dry_run=True))

        assert eventos_recebidos == []

    @patch("classificacao_procons.litigio.pipeline._consultar_djen")
    def test_should_not_call_handler_for_ciencia_only_intimacao(
        self,
        djen_mock,
        tmp_path: Path,
    ) -> None:
        djen_mock.return_value = [
            _intimacao(texto="Tomar ciência do despacho.", tipo_documento="Ato ordinatório"),
        ]

        eventos = monitorar_intimacoes(_options(tmp_path))

        assert len(eventos) == 1
        assert eventos[0].requer_atencao is False

    @patch("classificacao_procons.litigio.pipeline.register_or_update_processo")
    @patch("classificacao_procons.litigio.pipeline._consultar_djen")
    def test_should_register_on_monday_when_requer_atencao(
        self,
        djen_mock,
        monday_mock,
        tmp_path: Path,
    ) -> None:
        djen_mock.return_value = [_intimacao()]
        monday_mock.return_value = MondayLitigioResult(
            item_id="1",
            board_id="222",
            item_url="https://b4a.monday.com/boards/222/pulses/1",
            criado=True,
        )
        options = _options(tmp_path, register_on_monday=True)

        eventos = monitorar_intimacoes(options)

        assert monday_mock.call_count == 1
        assert eventos[0].monday_item_url == "https://b4a.monday.com/boards/222/pulses/1"

    @patch("classificacao_procons.litigio.pipeline.register_or_update_processo")
    @patch("classificacao_procons.litigio.pipeline._consultar_djen")
    def test_should_not_register_on_monday_for_ciencia_only_events(
        self,
        djen_mock,
        monday_mock,
        tmp_path: Path,
    ) -> None:
        djen_mock.return_value = [
            _intimacao(texto="Tomar ciência do despacho.", tipo_documento="Ato ordinatório"),
        ]
        options = _options(tmp_path, register_on_monday=True)

        monitorar_intimacoes(options)

        assert monday_mock.call_count == 0
