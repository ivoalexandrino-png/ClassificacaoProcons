"""Modelos de domínio do agente jurídico (intimações e andamento processual)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

NOTIFICATION_TYPE_CITACAO = "citacao"
NOTIFICATION_TYPE_INTIMACAO = "intimacao"
NOTIFICATION_TYPE_AUDIENCIA = "audiencia"
NOTIFICATION_TYPE_SENTENCA = "sentenca"
NOTIFICATION_TYPE_DECISAO = "decisao"

ACTION_CONTESTAR = "contestar"
ACTION_MANIFESTAR = "manifestar"
ACTION_COMPARECER_AUDIENCIA = "comparecer_audiencia"
ACTION_ANALISAR_RECURSO = "analisar_recurso"
ACTION_ACOMPANHAR_ANDAMENTO = "acompanhar_andamento"
ACTION_REVISAR_ANDAMENTO = "revisar_andamento"
ACTION_CUMPRIR_ACORDO = "cumprir_acordo"
ACTION_VERIFICAR_ENCERRAMENTO = "verificar_encerramento"
ACTION_VERIFICAR_SEGREDO = "verificar_segredo"
ACTION_TOMAR_CIENCIA = "tomar_ciencia"


@dataclass(frozen=True)
class JudicialNotificationEmail:
    """E-mail/push de intimação recebido na caixa do jurídico."""

    message_id: str
    subject: str
    sender: str
    received_at: datetime
    body_text: str
    raw_snippet: str | None = None


@dataclass(frozen=True)
class ParsedIntimacao:
    """Dados estruturados extraídos de uma intimação."""

    process_number: str
    notification_type: str
    tribunal: str | None = None
    court_unit: str | None = None
    deadline_days: int | None = None
    deadline_in_business_days: bool = True
    deadline_date: date | None = None
    hearing_datetime: datetime | None = None
    summary: str = ""
    # Push/publicação com gatilho de prazo (intimação publicada/expedida/lida,
    # carta entregue) mas sem o prazo explícito no texto.
    has_deadline_trigger: bool = False


@dataclass(frozen=True)
class Providencia:
    """Triagem da intimação: o que o jurídico precisa fazer e até quando."""

    action_type: str
    description: str
    requires_action: bool
    due_date: date | None = None
    hearing_datetime: datetime | None = None
    requires_legal_document: bool = False
    affects_contingency: bool = False
    stage_note: str | None = None


@dataclass(frozen=True)
class CaseMovement:
    """Andamento processual retornado pela API pública do DataJud/CNJ."""

    movement_name: str
    movement_code: int | None = None
    movement_datetime: datetime | None = None


@dataclass(frozen=True)
class CaseMetadata:
    """Metadados do processo no DataJud (sigilo, sistema, grau, classe)."""

    nivel_sigilo: int | None = None
    sistema: str | None = None
    grau: str | None = None
    classe: str | None = None

    @property
    def is_secret(self) -> bool:
        """Segredo de justiça: nível de sigilo maior que zero."""
        return self.nivel_sigilo is not None and self.nivel_sigilo > 0


@dataclass(frozen=True)
class CaseCommunication:
    """Comunicação do Domicílio Judicial Eletrônico (API Comunica do PJe/CNJ)."""

    text: str
    communication_type: str | None = None
    tribunal: str | None = None
    organ: str | None = None
    available_date: str | None = None
    link: str | None = None


@dataclass(frozen=True)
class CaseAnalysis:
    """Entendimento do caso: o que aconteceu e o que fazer."""

    text: str
    source: str  # "gemini" ou "heuristica"


@dataclass(frozen=True)
class ProcessedIntimacao:
    """Resultado do fluxo e-mail → triagem → Monday → eventos."""

    status: str
    message_id: str
    process_number: str
    notification_type: str
    action_type: str
    requires_action: bool
    due_date: date | None = None
    hearing_datetime: datetime | None = None
    tribunal: str | None = None
    court_unit: str | None = None
    summary: str = ""
    analysis: str = ""
    analysis_source: str = ""
    communications_count: int = 0
    stage_note: str | None = None
    monday_item_url: str | None = None
    monday_audiencia_url: str | None = None
    monday_prazo_skipped_duplicate: bool = False
    monday_error: str | None = None
    case_sync_note: str | None = None
    events_emitted: list[str] = field(default_factory=list)
    error: str | None = None
