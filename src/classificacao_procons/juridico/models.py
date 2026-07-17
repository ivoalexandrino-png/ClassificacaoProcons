"""Modelos de domínio do agente jurídico."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class IntimacaoEmail:
    """Dados extraídos de um e-mail de intimação/push processual."""

    message_id: str
    subject: str
    sender: str
    received_at: datetime
    process_number: str | None = None
    tribunal: str | None = None
    vara: str | None = None
    orgao: str | None = None
    movement_type: str | None = None
    prazo_dias: int | None = None
    prazo_uteis: bool = True
    publication_date: date | None = None
    hearing_at: datetime | None = None
    portal_url: str | None = None
    parties: str | None = None
    body_excerpt: str | None = None
    raw_snippet: str | None = None


@dataclass(frozen=True)
class Andamento:
    """Um movimento/andamento do processo (do e-mail ou do sistema de andamento)."""

    process_number: str
    description: str
    occurred_at: date | None = None
    source: str = "email"


@dataclass(frozen=True)
class ProcessoJudicial:
    """Dados consolidados de um processo judicial."""

    process_number: str
    tribunal: str | None = None
    vara: str | None = None
    parties: str | None = None
    portal_url: str | None = None
    andamentos: tuple[Andamento, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Providencia:
    """Providência a ser controlada pelo jurídico (prazo e/ou audiência)."""

    process_number: str
    tipo: str
    descricao: str
    prazo_final: date | None = None
    hearing_at: datetime | None = None
    requires_action: bool = True
    status: str = "A providenciar"


@dataclass(frozen=True)
class RegistroJuridicoResult:
    """Resultado completo do processamento de uma intimação."""

    status: str
    message_id: str
    process_number: str
    tipo: str
    descricao: str
    prazo_final: date | None = None
    hearing_at: datetime | None = None
    tribunal: str | None = None
    vara: str | None = None
    monday_item_url: str | None = None
    monday_error: str | None = None
    peca_status: str | None = None
    relatorio_status: str | None = None
    error: str | None = None
