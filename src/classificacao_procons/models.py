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
    protocol_number: str | None = None
    email_response_deadline: str | None = None
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


@dataclass(frozen=True)
class ProcessedComplaint:
    """Resultado completo do fluxo e-mail → portal → Drive."""

    status: str
    message_id: str
    access_code: str
    protocol_number: str
    consumer_name: str
    consumer_cpf: str
    complaint_date: date | None
    procon_response_deadline: date | None
    sac_deadline: date | None
    legal_deadline: date | None
    cause: str
    state: str
    pdf_url: str | None
    drive_folder_url: str | None
    monday_item_url: str | None = None
    monday_error: str | None = None
    error: str | None = None
