"""Testes do pipeline do agente jurídico (com mocks)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from classificacao_procons.juridico import pipeline as juridico_pipeline
from classificacao_procons.juridico.events import (
    EVENT_ATUALIZAR_CONTINGENCIA,
    EVENT_ELABORAR_PECA,
    list_events,
)
from classificacao_procons.juridico.models import JudicialNotificationEmail
from classificacao_procons.juridico.pipeline import (
    JuridicoPipelineError,
    JuridicoPipelineOptions,
    process_new_intimacoes,
)
from classificacao_procons.monday.client import MondayClientError, MondayRegistrationResult

CITACAO_BODY = (
    "Processo 1001234-56.2026.8.26.0100\n"
    "CITAÇÃO da empresa ré para apresentar contestação no prazo de 15 (quinze) dias úteis."
)


def _notification(
    message_id: str = "msg-001",
    body: str = CITACAO_BODY,
    subject: str = "Intimação eletrônica",
) -> JudicialNotificationEmail:
    return JudicialNotificationEmail(
        message_id=message_id,
        subject=subject,
        sender="naoresponda@tjsp.jus.br",
        received_at=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
        body_text=body,
    )


class FakeFetcher:
    def __init__(self, notifications: list[JudicialNotificationEmail]) -> None:
        self.notifications = notifications
        self.marked_read: list[str] = []

    def list_unread_notifications(self, *, max_results: int = 20):
        return self.notifications[:max_results]

    def mark_as_read(self, message_id: str) -> None:
        self.marked_read.append(message_id)


@pytest.fixture
def options(tmp_path: Path) -> JuridicoPipelineOptions:
    return JuridicoPipelineOptions(
        state_path=tmp_path / "state.json",
        events_path=tmp_path / "events.jsonl",
        monday_api_token="token-teste",
    )


def _patch_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    fetcher: FakeFetcher,
    *,
    registration: MondayRegistrationResult | Exception | None = None,
) -> list[dict]:
    register_calls: list[dict] = []

    def fake_register(**kwargs):
        register_calls.append(kwargs)
        if isinstance(registration, Exception):
            raise registration
        return registration

    monkeypatch.setattr(juridico_pipeline, "has_valid_token", lambda token_path: True)
    monkeypatch.setattr(juridico_pipeline, "has_gmail_modify_access", lambda token_path: True)
    monkeypatch.setattr(
        juridico_pipeline,
        "GmailJuridicoFetcher",
        SimpleNamespace(from_credentials=lambda **kwargs: fetcher),
    )
    monkeypatch.setattr(juridico_pipeline, "register_providencia", fake_register)
    monkeypatch.setattr(juridico_pipeline, "get_api_key_from_env", lambda: None)
    return register_calls


class TestProcessNewIntimacoes:
    def test_should_process_citacao_end_to_end(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        fetcher = FakeFetcher([_notification()])
        registration = MondayRegistrationResult(
            item_id="777",
            board_id="123",
            item_url="https://empresa.monday.com/boards/123/pulses/777",
        )
        register_calls = _patch_pipeline(monkeypatch, fetcher, registration=registration)

        results = process_new_intimacoes(options)

        assert len(results) == 1
        result = results[0]
        assert result.status == "success"
        assert result.process_number == "1001234-56.2026.8.26.0100"
        assert result.action_type == "contestar"
        assert result.requires_action is True
        assert result.due_date is not None
        assert result.due_date.isoformat() == "2026-08-07"
        assert result.monday_item_url == "https://empresa.monday.com/boards/123/pulses/777"
        assert sorted(result.events_emitted) == [
            EVENT_ATUALIZAR_CONTINGENCIA,
            EVENT_ELABORAR_PECA,
        ]

        assert len(register_calls) == 1
        assert fetcher.marked_read == ["msg-001"]

        state = json.loads(options.state_path.read_text(encoding="utf-8"))
        assert state["message_ids"] == ["msg-001"]

        peca_events = list_events(
            events_path=options.events_path,
            event_type=EVENT_ELABORAR_PECA,
        )
        assert len(peca_events) == 1
        assert peca_events[0].action_type == "contestar"
        assert peca_events[0].due_date == "2026-08-07"

    def test_should_skip_message_already_processed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        fetcher = FakeFetcher([_notification()])
        _patch_pipeline(monkeypatch, fetcher, registration=None)
        options.state_path.parent.mkdir(parents=True, exist_ok=True)
        options.state_path.write_text(
            json.dumps({"message_ids": ["msg-001"]}),
            encoding="utf-8",
        )

        results = process_new_intimacoes(options)

        assert results[0].status == "skipped_duplicate"
        assert fetcher.marked_read == []
        assert not options.events_path.exists()

    def test_should_not_touch_external_services_on_dry_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        fetcher = FakeFetcher([_notification()])
        register_calls = _patch_pipeline(monkeypatch, fetcher, registration=None)

        dry_options = JuridicoPipelineOptions(
            state_path=options.state_path,
            events_path=options.events_path,
            dry_run=True,
        )
        results = process_new_intimacoes(dry_options)

        assert results[0].status == "dry_run"
        assert results[0].action_type == "contestar"
        assert register_calls == []
        assert fetcher.marked_read == []
        assert not options.state_path.exists()
        assert not options.events_path.exists()

    def test_should_report_monday_error_without_losing_events(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        fetcher = FakeFetcher([_notification()])
        _patch_pipeline(
            monkeypatch,
            fetcher,
            registration=MondayClientError("board não encontrado"),
        )

        results = process_new_intimacoes(options)

        assert results[0].status == "success"
        assert results[0].monday_error == "board não encontrado"
        assert results[0].monday_item_url is None
        assert len(list_events(events_path=options.events_path)) == 2

    def test_should_return_error_when_process_number_is_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        fetcher = FakeFetcher(
            [_notification(body="Intimação sem número de processo.", subject="Intimação")],
        )
        _patch_pipeline(monkeypatch, fetcher, registration=None)

        results = process_new_intimacoes(options)

        assert results[0].status == "error"
        assert results[0].error is not None
        assert "Número de processo" in results[0].error

    def test_should_not_register_on_monday_when_only_ciencia(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        fetcher = FakeFetcher(
            [
                _notification(
                    body=(
                        "Processo 1001234-56.2026.8.26.0100. "
                        "Processo arquivado definitivamente."
                    ),
                ),
            ],
        )
        register_calls = _patch_pipeline(monkeypatch, fetcher, registration=None)

        results = process_new_intimacoes(options)

        assert results[0].status == "success"
        assert results[0].requires_action is False
        assert register_calls == []
        # ciência ainda alimenta o agente futuro de contingência
        events = list_events(events_path=options.events_path)
        assert [event.event_type for event in events] == [EVENT_ATUALIZAR_CONTINGENCIA]

    def test_should_raise_when_google_token_is_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        monkeypatch.setattr(juridico_pipeline, "has_valid_token", lambda token_path: False)
        with pytest.raises(JuridicoPipelineError, match="Google não conectado"):
            process_new_intimacoes(options)
