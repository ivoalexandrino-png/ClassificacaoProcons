"""Testes da fila de eventos de handoff (JSONL)."""

from pathlib import Path

import pytest

from classificacao_procons.juridico.events import (
    EVENT_ATUALIZAR_CONTINGENCIA,
    EVENT_ELABORAR_PECA,
    AgentEvent,
    AgentEventError,
    emit_event,
    list_events,
)


def _event(event_type: str = EVENT_ELABORAR_PECA) -> AgentEvent:
    return AgentEvent(
        event_type=event_type,
        process_number="1001234-83.2026.8.26.0100",
        action_type="contestar",
        due_date="2026-08-07",
        payload={"summary": "citação recebida"},
    )


class TestEmitEvent:
    def test_should_append_event_and_stamp_created_at(self, tmp_path: Path) -> None:
        events_path = tmp_path / "events.jsonl"
        stamped = emit_event(_event(), events_path=events_path)

        assert stamped.created_at != ""
        stored = list_events(events_path=events_path)
        assert len(stored) == 1
        assert stored[0].process_number == "1001234-83.2026.8.26.0100"
        assert stored[0].payload == {"summary": "citação recebida"}

    def test_should_append_multiple_events_in_order(self, tmp_path: Path) -> None:
        events_path = tmp_path / "events.jsonl"
        emit_event(_event(EVENT_ELABORAR_PECA), events_path=events_path)
        emit_event(_event(EVENT_ATUALIZAR_CONTINGENCIA), events_path=events_path)

        stored = list_events(events_path=events_path)
        assert [item.event_type for item in stored] == [
            EVENT_ELABORAR_PECA,
            EVENT_ATUALIZAR_CONTINGENCIA,
        ]

    def test_should_raise_when_event_type_is_unknown(self, tmp_path: Path) -> None:
        with pytest.raises(AgentEventError, match="Tipo de evento desconhecido"):
            emit_event(_event("tipo_invalido"), events_path=tmp_path / "events.jsonl")


class TestListEvents:
    def test_should_return_empty_list_when_file_is_missing(self, tmp_path: Path) -> None:
        assert list_events(events_path=tmp_path / "nao-existe.jsonl") == []

    def test_should_filter_by_event_type(self, tmp_path: Path) -> None:
        events_path = tmp_path / "events.jsonl"
        emit_event(_event(EVENT_ELABORAR_PECA), events_path=events_path)
        emit_event(_event(EVENT_ATUALIZAR_CONTINGENCIA), events_path=events_path)

        stored = list_events(events_path=events_path, event_type=EVENT_ATUALIZAR_CONTINGENCIA)
        assert len(stored) == 1
        assert stored[0].event_type == EVENT_ATUALIZAR_CONTINGENCIA

    def test_should_raise_when_filter_type_is_unknown(self, tmp_path: Path) -> None:
        with pytest.raises(AgentEventError, match="Tipo de evento desconhecido"):
            list_events(events_path=tmp_path / "events.jsonl", event_type="qualquer")

    def test_should_raise_when_line_is_invalid_json(self, tmp_path: Path) -> None:
        events_path = tmp_path / "events.jsonl"
        events_path.write_text("{nao é json}\n", encoding="utf-8")
        with pytest.raises(AgentEventError, match="Linha inválida"):
            list_events(events_path=events_path)
