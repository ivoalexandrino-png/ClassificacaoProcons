"""Triagem de intimações: qual providência tomar e até quando."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Final

from classificacao_procons.juridico.models import (
    ACTION_ACOMPANHAR_ANDAMENTO,
    ACTION_ANALISAR_RECURSO,
    ACTION_COMPARECER_AUDIENCIA,
    ACTION_CONTESTAR,
    ACTION_CUMPRIR_ACORDO,
    ACTION_MANIFESTAR,
    ACTION_REVISAR_ANDAMENTO,
    ACTION_TOMAR_CIENCIA,
    ACTION_VERIFICAR_ENCERRAMENTO,
    NOTIFICATION_TYPE_AUDIENCIA,
    NOTIFICATION_TYPE_CITACAO,
    NOTIFICATION_TYPE_SENTENCA,
    CaseMovement,
    ParsedIntimacao,
    Providencia,
)
from classificacao_procons.juridico.prazos import compute_due_date

DEFAULT_CONTESTACAO_DAYS: Final = 15
DEFAULT_RECURSO_DAYS: Final = 15
DEFAULT_MANIFESTACAO_DAYS: Final = 5
# Prazo curto para revisar intimação publicada sem prazo explícito no push:
# o menor prazo processual comum é de 5 dias úteis — revisar antes disso.
DEFAULT_REVISAO_DAYS: Final = 3

ACTION_LABELS: Final[dict[str, str]] = {
    ACTION_CONTESTAR: "Apresentar contestação",
    ACTION_MANIFESTAR: "Apresentar manifestação",
    ACTION_COMPARECER_AUDIENCIA: "Preparar e comparecer à audiência",
    ACTION_ANALISAR_RECURSO: "Analisar sentença e avaliar recurso",
    ACTION_ACOMPANHAR_ANDAMENTO: "Acompanhar andamento do processo",
    ACTION_REVISAR_ANDAMENTO: "Revisar intimação e confirmar prazo",
    ACTION_CUMPRIR_ACORDO: "Acompanhar cumprimento do acordo homologado",
    ACTION_VERIFICAR_ENCERRAMENTO: "Verificar encerramento e obrigações finais",
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

# Marcos de estágio processual (nome TPU/DataJud, normalizado), do mais
# avançado para o mais inicial. O agente detecta o marco mais avançado nos
# andamentos e o usa tanto para saber se a providência do e-mail já foi
# superada quanto para definir a providência específica daquele estágio.
STAGE_ENCERRAMENTO = "encerramento"
STAGE_ACORDO = "acordo"
STAGE_SENTENCA = "sentenca"
STAGE_CONTESTACAO = "contestacao"

_STAGE_MARKER_KEYWORDS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        STAGE_ENCERRAMENTO,
        ("transito em julgado", "arquivamento", "baixa definitiva", "extincao"),
    ),
    (
        STAGE_ACORDO,
        ("homologacao de transacao", "homologacao do acordo", "acordo homologado"),
    ),
    (STAGE_SENTENCA, ("sentenca", "procedencia", "improcedencia")),
    (STAGE_CONTESTACAO, ("contestacao",)),
)

# Estágios que tornam cada providência de e-mail obsoleta (push atrasado).
_SUPERSEDED_BY_STAGES: Final[dict[str, frozenset[str]]] = {
    ACTION_CONTESTAR: frozenset(
        {STAGE_CONTESTACAO, STAGE_SENTENCA, STAGE_ACORDO, STAGE_ENCERRAMENTO},
    ),
    ACTION_MANIFESTAR: frozenset({STAGE_ENCERRAMENTO}),
    ACTION_REVISAR_ANDAMENTO: frozenset({STAGE_ACORDO, STAGE_ENCERRAMENTO}),
    ACTION_ANALISAR_RECURSO: frozenset({STAGE_ACORDO, STAGE_ENCERRAMENTO}),
}

# Providência específica de cada estágio + prazo de acompanhamento padrão
# (dias úteis a partir do recebimento do push). O prazo de recurso é o legal
# (15 dias úteis); os demais são datas operacionais de acompanhamento.
_STAGE_RECLASSIFICATION: Final[dict[str, tuple[str, int]]] = {
    STAGE_ENCERRAMENTO: (ACTION_VERIFICAR_ENCERRAMENTO, 5),
    STAGE_ACORDO: (ACTION_CUMPRIR_ACORDO, 10),
    STAGE_SENTENCA: (ACTION_ANALISAR_RECURSO, 15),
    STAGE_CONTESTACAO: (ACTION_ACOMPANHAR_ANDAMENTO, 10),
}

# Push de mera ciência (ou de revisão sem prazo explícito) só vira providência
# específica se o marco for recente (evita reabrir sentenças/acordos antigos a
# cada push genérico).
_CIENCIA_UPGRADE_ACTIONS: Final[frozenset[str]] = frozenset(
    {ACTION_TOMAR_CIENCIA, ACTION_REVISAR_ANDAMENTO},
)
_CIENCIA_UPGRADE_STAGES: Final[frozenset[str]] = frozenset(
    {STAGE_ENCERRAMENTO, STAGE_ACORDO, STAGE_SENTENCA},
)
_CIENCIA_UPGRADE_MAX_AGE_DAYS: Final = 30

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
    "homologacao de transacao",
    "homologacao do acordo",
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
    if intimacao.has_deadline_trigger:
        # Intimação publicada/expedida/lida sem o prazo no texto: há prazo
        # correndo, mas só o teor diz qual — item para revisão com data curta.
        return ACTION_REVISAR_ANDAMENTO
    return ACTION_TOMAR_CIENCIA


def _default_deadline_days(action_type: str) -> int | None:
    if action_type == ACTION_CONTESTAR:
        return DEFAULT_CONTESTACAO_DAYS
    if action_type == ACTION_ANALISAR_RECURSO:
        return DEFAULT_RECURSO_DAYS
    if action_type == ACTION_MANIFESTAR:
        return DEFAULT_MANIFESTACAO_DAYS
    if action_type == ACTION_REVISAR_ANDAMENTO:
        return DEFAULT_REVISAO_DAYS
    return None


def affects_contingency(text: str) -> bool:
    """Andamentos com impacto financeiro (depósitos, penhoras, condenações)."""
    normalized = _normalize(text)
    return any(keyword in normalized for keyword in CONTINGENCY_KEYWORDS)


def detect_process_stage(
    movements: list[CaseMovement],
) -> tuple[str, CaseMovement] | None:
    """Marco de estágio mais avançado presente nos andamentos do DataJud."""
    for stage, keywords in _STAGE_MARKER_KEYWORDS:
        for movement in movements:
            normalized = _normalize(movement.movement_name)
            if any(keyword in normalized for keyword in keywords):
                return stage, movement
    return None


def _movement_moment(movement: CaseMovement) -> str:
    if movement.movement_datetime:
        return movement.movement_datetime.strftime("%d/%m/%Y")
    return "data não informada"


def _providencia_for_stage(
    *,
    stage: str,
    marker: CaseMovement,
    original: Providencia,
    base_date: date,
    reason: str,
) -> Providencia:
    action_type, deadline_days = _STAGE_RECLASSIFICATION[stage]
    description = ACTION_LABELS[action_type]
    due_date = compute_due_date(
        base_date=base_date,
        deadline_days=deadline_days,
        in_business_days=True,
        explicit_date=None,
    )
    prazo_kind = "prazo legal estimado" if stage == STAGE_SENTENCA else "acompanhamento até"
    stage_note = (
        f'{reason} O DataJud mostra "{marker.movement_name}" em {_movement_moment(marker)}. '
        f"Providência: {description} ({prazo_kind} "
        f"{due_date.strftime('%d/%m/%Y') if due_date else 'sem data'}, contado do "
        "recebimento do push — confirme a data de intimação no tribunal)."
    )
    return Providencia(
        action_type=action_type,
        description=description,
        requires_action=True,
        due_date=due_date,
        hearing_datetime=original.hearing_datetime,
        requires_legal_document=action_type in _LEGAL_DOCUMENT_ACTIONS,
        affects_contingency=(
            original.affects_contingency or affects_contingency(marker.movement_name)
        ),
        stage_note=stage_note,
    )


def _is_recent_marker(marker: CaseMovement, *, base_date: date) -> bool:
    if marker.movement_datetime is None:
        return False
    age_days = (base_date - marker.movement_datetime.date()).days
    return age_days <= _CIENCIA_UPGRADE_MAX_AGE_DAYS


def reclassify_providencia_from_movements(
    providencia: Providencia,
    movements: list[CaseMovement],
    *,
    base_date: date,
) -> Providencia:
    """Ajusta a providência ao estágio real do processo (andamentos do DataJud).

    Dois caminhos:

    - **Providência do e-mail superada** (ex.: push de citação de processo que
      já tem contestação, acordo ou sentença): em vez de só "tomar ciência", o
      agente cadastra a providência específica do estágio atual — acompanhar o
      acordo, analisar a sentença, verificar o encerramento — com prazo.
    - **Push de mera ciência** com marco recente (sentença/acordo/encerramento
      nos últimos 30 dias): vira a providência específica do marco, para o
      andamento não passar despercebido.
    """
    detected = detect_process_stage(movements)
    if detected is None:
        return providencia
    stage, marker = detected

    superseded_by = _SUPERSEDED_BY_STAGES.get(providencia.action_type, frozenset())
    if stage in superseded_by:
        return _providencia_for_stage(
            stage=stage,
            marker=marker,
            original=providencia,
            base_date=base_date,
            reason=(
                f'Providência "{providencia.description}" substituída: '
                "o processo já passou desse estágio."
            ),
        )

    if (
        providencia.action_type in _CIENCIA_UPGRADE_ACTIONS
        and stage in _CIENCIA_UPGRADE_STAGES
        and _is_recent_marker(marker, base_date=base_date)
    ):
        return _providencia_for_stage(
            stage=stage,
            marker=marker,
            original=providencia,
            base_date=base_date,
            reason="Andamento relevante detectado no processo.",
        )

    return providencia


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
