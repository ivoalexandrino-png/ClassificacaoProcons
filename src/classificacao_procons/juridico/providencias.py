"""Triagem de intimações: qual providência tomar e até quando."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Final

from classificacao_procons.juridico.models import (
    ACTION_ANALISAR_RECURSO,
    ACTION_COMPARECER_AUDIENCIA,
    ACTION_CONTESTAR,
    ACTION_MANIFESTAR,
    ACTION_TOMAR_CIENCIA,
    NOTIFICATION_TYPE_AUDIENCIA,
    NOTIFICATION_TYPE_CITACAO,
    NOTIFICATION_TYPE_SENTENCA,
    ParsedIntimacao,
    Providencia,
)
from classificacao_procons.juridico.prazos import compute_due_date

DEFAULT_CONTESTACAO_DAYS: Final = 15
DEFAULT_RECURSO_DAYS: Final = 15
DEFAULT_MANIFESTACAO_DAYS: Final = 5

ACTION_LABELS: Final[dict[str, str]] = {
    ACTION_CONTESTAR: "Apresentar contestação",
    ACTION_MANIFESTAR: "Apresentar manifestação",
    ACTION_COMPARECER_AUDIENCIA: "Preparar e comparecer à audiência",
    ACTION_ANALISAR_RECURSO: "Analisar sentença e avaliar recurso",
    ACTION_TOMAR_CIENCIA: "Tomar ciência do andamento",
}

_LEGAL_DOCUMENT_ACTIONS: Final = frozenset(
    {ACTION_CONTESTAR, ACTION_MANIFESTAR, ACTION_ANALISAR_RECURSO},
)

_MANIFESTATION_KEYWORDS: Final[tuple[str, ...]] = (
    "manifest",
    "impugna",
    "emenda",
    "esclarecimento",
    "junte",
    "juntada de documentos",
    "replica",
    "contrarrazoes",
    "cumprimento de sentenca",
)

_NO_ACTION_KEYWORDS: Final[tuple[str, ...]] = (
    "arquivado",
    "arquivamento",
    "baixa definitiva",
    "transito em julgado",
    "mera ciencia",
    "apenas para ciencia",
    "sem necessidade de manifestacao",
)

CONTINGENCY_KEYWORDS: Final[tuple[str, ...]] = (
    "deposito",
    "deposito judicial",
    "penhora",
    "bloqueio",
    "sisbajud",
    "bacenjud",
    "alvara",
    "garantia do juizo",
    "provisao",
    "condenacao",
    "pagamento",
    "execucao",
    "cumprimento de sentenca",
    "acordo homologado",
)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


def _detect_action(intimacao: ParsedIntimacao, normalized_summary: str) -> str:
    if intimacao.notification_type == NOTIFICATION_TYPE_CITACAO:
        return ACTION_CONTESTAR
    if intimacao.notification_type == NOTIFICATION_TYPE_AUDIENCIA or intimacao.hearing_datetime:
        return ACTION_COMPARECER_AUDIENCIA
    if intimacao.notification_type == NOTIFICATION_TYPE_SENTENCA:
        return ACTION_ANALISAR_RECURSO
    if any(keyword in normalized_summary for keyword in _MANIFESTATION_KEYWORDS):
        return ACTION_MANIFESTAR
    if intimacao.deadline_days is not None or intimacao.deadline_date is not None:
        return ACTION_MANIFESTAR
    return ACTION_TOMAR_CIENCIA


def _default_deadline_days(action_type: str) -> int | None:
    if action_type == ACTION_CONTESTAR:
        return DEFAULT_CONTESTACAO_DAYS
    if action_type == ACTION_ANALISAR_RECURSO:
        return DEFAULT_RECURSO_DAYS
    if action_type == ACTION_MANIFESTAR:
        return DEFAULT_MANIFESTACAO_DAYS
    return None


def affects_contingency(text: str) -> bool:
    """Andamentos com impacto financeiro (depósitos, penhoras, condenações)."""
    normalized = _normalize(text)
    return any(keyword in normalized for keyword in CONTINGENCY_KEYWORDS)


def classify_providencia(intimacao: ParsedIntimacao, *, base_date: date) -> Providencia:
    """Define ação, prazo fatal e sinais de handoff para os agentes futuros."""
    normalized_summary = _normalize(intimacao.summary)

    if any(keyword in normalized_summary for keyword in _NO_ACTION_KEYWORDS):
        action_type = ACTION_TOMAR_CIENCIA
    else:
        action_type = _detect_action(intimacao, normalized_summary)

    deadline_days = intimacao.deadline_days
    if deadline_days is None and intimacao.deadline_date is None:
        deadline_days = _default_deadline_days(action_type)

    due_date = compute_due_date(
        base_date=base_date,
        deadline_days=deadline_days,
        in_business_days=intimacao.deadline_in_business_days,
        explicit_date=intimacao.deadline_date,
    )

    if action_type == ACTION_COMPARECER_AUDIENCIA and due_date is None:
        hearing = intimacao.hearing_datetime
        due_date = hearing.date() if hearing else None

    requires_action = action_type != ACTION_TOMAR_CIENCIA

    return Providencia(
        action_type=action_type,
        description=ACTION_LABELS[action_type],
        requires_action=requires_action,
        due_date=due_date,
        hearing_datetime=intimacao.hearing_datetime,
        requires_legal_document=action_type in _LEGAL_DOCUMENT_ACTIONS,
        affects_contingency=affects_contingency(intimacao.summary),
    )
