"""Modelos do agente WhatsApp."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

RiskTier = Literal["routine", "ambiguous", "legal_high"]


@dataclass(frozen=True)
class ChatTurn:
    """Uma mensagem em um diálogo (entrada ou saída)."""

    role: Literal["contact", "owner", "assistant"]
    text: str
    message_id: str | None = None
    timestamp_ms: int | None = None


@dataclass
class ConversationThread:
    """Histórico recente de um chat."""

    chat_id: str
    contact_label: str | None = None
    turns: list[ChatTurn] = field(default_factory=list)


@dataclass(frozen=True)
class IncomingMessage:
    """Mensagem recebida normalizada (independente do transporte)."""

    chat_id: str
    message_id: str
    text: str
    contact_label: str | None
    timestamp_ms: int | None
    is_group: bool


@dataclass(frozen=True)
class ReplyPlan:
    """Plano de resposta antes do envio."""

    tier: RiskTier
    reply_text: str
    reasons: tuple[str, ...] = ()
    used_history: bool = False


@dataclass
class BotState:
    """Estado persistente (dedup + threads)."""

    processed_message_ids: frozenset[str] = frozenset()
    threads: dict[str, ConversationThread] = field(default_factory=dict)
