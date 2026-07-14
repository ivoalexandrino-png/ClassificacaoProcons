"""Modelos de domínio para notificações do Procon."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ProconNotificationEmail:
    """Dados extraídos de um e-mail de notificação de CIP do Procon-SP."""

    message_id: str
    subject: str
    sender: str
    received_at: datetime
    portal_url: str
    access_code: str
    raw_snippet: str | None = None
