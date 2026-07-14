"""Modelos de domínio para reclamações do Procon."""

from dataclasses import dataclass
from datetime import date, datetime


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


@dataclass(frozen=True)
class ProconComplaint:
    """Dados extraídos do portal do Procon-SP."""

    access_code: str
    consumer_name: str
    consumer_cpf: str
    cip_fa_number: str
    complaint_date: date | None
    response_deadline: date | None
    cause: str
    state: str = "SP"
    portal_url: str = ""
    pdf_path: str | None = None
