"""Pontos de integração com os dois futuros agentes do jurídico.

O agente jurídico deste repositório cuida da triagem (intimação → providência →
Monday). Ele foi desenhado para, no futuro, delegar trabalho a dois agentes
ainda inexistentes, sem que o pipeline precise mudar:

1. :class:`PecaProcessualAgent` — elabora e protocola peças processuais a partir
   de uma providência com prazo.
2. :class:`RelatorioContingenciaAgent` — atualiza relatórios contingenciais com
   andamentos, depósitos, provisões etc.

As implementações reais desses agentes viverão em outros serviços/repos. Aqui
definimos apenas as interfaces (``Protocol``) e implementações nulas seguras
(no-op) para que o pipeline funcione hoje e ganhe comportamento amanhã, bastando
injetar as implementações concretas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from classificacao_procons.juridico.models import Andamento, ProcessoJudicial, Providencia


@dataclass(frozen=True)
class PecaResult:
    """Resultado da elaboração/protocolo de uma peça pelo agente futuro."""

    status: str
    detail: str | None = None
    peca_url: str | None = None
    protocol_number: str | None = None


@dataclass(frozen=True)
class RelatorioResult:
    """Resultado da atualização do relatório contingencial pelo agente futuro."""

    status: str
    detail: str | None = None
    relatorio_url: str | None = None


@runtime_checkable
class PecaProcessualAgent(Protocol):
    """Agente futuro que elabora e protocola peças processuais."""

    def draft_and_file(self, processo: ProcessoJudicial, providencia: Providencia) -> PecaResult:
        """Elabora (e, quando aplicável, protocola) a peça da providência."""
        ...


@runtime_checkable
class RelatorioContingenciaAgent(Protocol):
    """Agente futuro que atualiza relatórios contingenciais."""

    def update_report(self, processo: ProcessoJudicial, andamento: Andamento) -> RelatorioResult:
        """Atualiza o relatório contingencial com o andamento do processo."""
        ...


class NullPecaProcessualAgent:
    """Implementação nula: sinaliza que a elaboração de peças está pendente."""

    STATUS = "pendente_integracao"

    def draft_and_file(self, processo: ProcessoJudicial, providencia: Providencia) -> PecaResult:
        del processo, providencia
        return PecaResult(
            status=self.STATUS,
            detail="Agente de elaboração/protocolo de peças ainda não integrado.",
        )


class NullRelatorioContingenciaAgent:
    """Implementação nula: sinaliza que o relatório contingencial está pendente."""

    STATUS = "pendente_integracao"

    def update_report(self, processo: ProcessoJudicial, andamento: Andamento) -> RelatorioResult:
        del processo, andamento
        return RelatorioResult(
            status=self.STATUS,
            detail="Agente de relatórios contingenciais ainda não integrado.",
        )
