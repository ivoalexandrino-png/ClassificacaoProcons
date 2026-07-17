"""Acesso ao sistema de andamento processual.

O jurídico acompanha o andamento dos processos em sistemas como PJe, e-SAJ,
Projudi, entre outros. Como cada tribunal expõe o andamento de forma diferente
(e muitos exigem certificado/login), o acesso é modelado como uma interface
plugável (:class:`AndamentoSource`).

- :class:`EmailAndamentoSource` — fonte padrão, offline: usa o próprio e-mail
  de intimação como andamento. É o suficiente para o MVP, já que o push já
  carrega o movimento relevante.
- :class:`PlaywrightAndamentoSource` — esqueleto para, no futuro, raspar o
  portal do tribunal (mesmo padrão do módulo ``portal`` do Procon). Ainda não
  implementado; documenta o ponto de extensão.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from classificacao_procons.juridico.models import Andamento, IntimacaoEmail


@runtime_checkable
class AndamentoSource(Protocol):
    """Fonte de andamentos de um processo."""

    def fetch_andamentos(self, intimacao: IntimacaoEmail) -> list[Andamento]:
        """Retorna os andamentos conhecidos do processo da intimação."""
        ...


class EmailAndamentoSource:
    """Deriva o andamento diretamente do e-mail de intimação (offline)."""

    def fetch_andamentos(self, intimacao: IntimacaoEmail) -> list[Andamento]:
        if not intimacao.process_number:
            return []
        description = intimacao.movement_type or "Intimação recebida"
        if intimacao.body_excerpt:
            description = f"{description}: {intimacao.body_excerpt}"
        return [
            Andamento(
                process_number=intimacao.process_number,
                description=description,
                occurred_at=intimacao.publication_date,
                source="email",
            ),
        ]


class PlaywrightAndamentoSource:
    """Ponto de extensão para raspar o portal do tribunal (não implementado).

    Deve seguir o mesmo padrão de ``classificacao_procons.portal.client`` do
    fluxo Procon: abrir o portal via Playwright, autenticar e ler a árvore de
    andamentos. Requer credenciais/certificado do tribunal.
    """

    def __init__(self, *, headless: bool = True) -> None:
        self.headless = headless

    def fetch_andamentos(self, intimacao: IntimacaoEmail) -> list[Andamento]:
        raise NotImplementedError(
            "Raspagem do portal de andamento processual ainda não implementada. "
            "Use EmailAndamentoSource ou implemente o acesso ao PJe/e-SAJ do tribunal.",
        )
