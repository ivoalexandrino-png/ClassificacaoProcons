"""Modelos de domínio para monitoramento de processos judiciais (litígio)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class ProvidenciaTipo(StrEnum):
    """Classificação da ação exigida por uma intimação."""

    AUDIENCIA = "audiencia"
    MANIFESTACAO = "manifestacao"
    RECURSO = "recurso"
    PAGAMENTO_DEPOSITO = "pagamento_deposito"
    CIENCIA = "ciencia"
    INDEFINIDA = "indefinida"


@dataclass(frozen=True)
class AdvogadoDestinatario:
    """Advogado destinatário de uma comunicação do DJEN."""

    nome: str
    numero_oab: str
    uf_oab: str


@dataclass(frozen=True)
class Intimacao:
    """Comunicação processual (intimação/citação/despacho) extraída do DJEN."""

    id: int
    hash: str
    numero_processo: str
    numero_processo_formatado: str
    tribunal: str
    tipo_comunicacao: str
    tipo_documento: str
    orgao: str
    classe_processual: str
    data_disponibilizacao: date
    texto: str
    link: str | None = None
    status: str | None = None
    motivo_cancelamento: str | None = None
    advogados: tuple[AdvogadoDestinatario, ...] = field(default_factory=tuple)

    @property
    def cancelada(self) -> bool:
        return bool(self.motivo_cancelamento)

    @property
    def certidao_url(self) -> str:
        return f"https://comunicaapi.pje.jus.br/api/v1/comunicacao/{self.hash}/certidao"


@dataclass(frozen=True)
class Providencia:
    """Resultado da análise de uma intimação: o que precisa ser feito e até quando."""

    intimacao_id: int
    numero_processo: str
    tipo: ProvidenciaTipo
    descricao: str
    requer_atencao: bool
    prazo_dias: int | None = None
    prazo_data: date | None = None
    data_audiencia: date | None = None


@dataclass(frozen=True)
class EventoProcesso:
    """Evento consolidado de uma intimação processada, pronto para Monday e para
    consumo pelos futuros agentes de peças processuais e de relatórios contingenciais."""

    numero_processo: str
    numero_processo_formatado: str
    tribunal: str
    tipo_providencia: ProvidenciaTipo
    descricao: str
    requer_atencao: bool
    intimacao_id: int
    data_disponibilizacao: date
    prazo_data: date | None
    data_audiencia: date | None
    certidao_url: str
    link_tribunal: str | None
    monday_item_url: str | None = None
    monday_error: str | None = None
