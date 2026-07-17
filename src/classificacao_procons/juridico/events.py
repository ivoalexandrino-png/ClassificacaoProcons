"""Fila de eventos (JSONL) para os agentes futuros de peças e contingência.

Cada intimação processada pode emitir eventos que serão consumidos por dois
agentes ainda não implementados:

- ``elaborar_peca`` — agente que vai elaborar e protocolizar peças processuais;
- ``atualizar_contingencia`` — agente que vai atualizar relatórios
  contingenciais (andamentos, depósitos, provisões).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

EVENT_ELABORAR_PECA = "elaborar_peca"
EVENT_ATUALIZAR_CONTINGENCIA = "atualizar_contingencia"
KNOWN_EVENT_TYPES = (EVENT_ELABORAR_PECA, EVENT_ATUALIZAR_CONTINGENCIA)

DEFAULT_EVENTS_PATH = Path("data/juridico-events.jsonl")


class AgentEventError(RuntimeError):
    """Erro ao emitir ou ler eventos de handoff."""


@dataclass(frozen=True)
class AgentEvent:
    """Evento de handoff destinado a um agente futuro."""

    event_type: str
    process_number: str
    action_type: str
    created_at: str = ""
    due_date: str | None = None
    monday_item_url: str | None = None
    payload: dict[str, object] = field(default_factory=dict)


def _validate_event_type(event_type: str) -> None:
    if event_type not in KNOWN_EVENT_TYPES:
        raise AgentEventError(
            f"Tipo de evento desconhecido: {event_type!r}. "
            f"Tipos válidos: {', '.join(KNOWN_EVENT_TYPES)}.",
        )


def emit_event(event: AgentEvent, *, events_path: Path = DEFAULT_EVENTS_PATH) -> AgentEvent:
    """Acrescenta o evento ao arquivo JSONL (append-only)."""
    _validate_event_type(event.event_type)
    stamped = AgentEvent(
        event_type=event.event_type,
        process_number=event.process_number,
        action_type=event.action_type,
        created_at=event.created_at or datetime.now(UTC).isoformat(),
        due_date=event.due_date,
        monday_item_url=event.monday_item_url,
        payload=event.payload,
    )
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(stamped), ensure_ascii=False) + "\n")
    return stamped


def list_events(
    *,
    events_path: Path = DEFAULT_EVENTS_PATH,
    event_type: str | None = None,
) -> list[AgentEvent]:
    """Lê os eventos emitidos, opcionalmente filtrando por tipo."""
    if event_type is not None:
        _validate_event_type(event_type)
    if not events_path.exists():
        return []

    events: list[AgentEvent] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise AgentEventError(f"Linha inválida em {events_path}: {stripped[:80]}") from exc
        event = AgentEvent(
            event_type=str(data.get("event_type", "")),
            process_number=str(data.get("process_number", "")),
            action_type=str(data.get("action_type", "")),
            created_at=str(data.get("created_at", "")),
            due_date=data.get("due_date"),
            monday_item_url=data.get("monday_item_url"),
            payload=data.get("payload") or {},
        )
        if event_type is None or event.event_type == event_type:
            events.append(event)
    return events
