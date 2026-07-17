"""Testes das interfaces dos agentes futuros do jurídico."""

from datetime import date

from classificacao_procons.juridico.agents import (
    NullPecaProcessualAgent,
    NullRelatorioContingenciaAgent,
    PecaProcessualAgent,
    RelatorioContingenciaAgent,
)
from classificacao_procons.juridico.models import Andamento, ProcessoJudicial, Providencia


def _processo() -> ProcessoJudicial:
    return ProcessoJudicial(process_number="1023456-78.2026.8.26.0100", tribunal="TJSP")


def _providencia() -> Providencia:
    return Providencia(
        process_number="1023456-78.2026.8.26.0100",
        tipo="Contestar",
        descricao="Contestar — TJSP",
        prazo_final=date(2026, 8, 7),
    )


class TestNullPecaAgent:
    def test_should_return_pending_status(self) -> None:
        result = NullPecaProcessualAgent().draft_and_file(_processo(), _providencia())
        assert result.status == "pendente_integracao"
        assert result.detail

    def test_should_satisfy_protocol(self) -> None:
        assert isinstance(NullPecaProcessualAgent(), PecaProcessualAgent)


class TestNullRelatorioAgent:
    def test_should_return_pending_status(self) -> None:
        andamento = Andamento(process_number="1023456-78.2026.8.26.0100", description="Sentença")
        result = NullRelatorioContingenciaAgent().update_report(_processo(), andamento)
        assert result.status == "pendente_integracao"

    def test_should_satisfy_protocol(self) -> None:
        assert isinstance(NullRelatorioContingenciaAgent(), RelatorioContingenciaAgent)
