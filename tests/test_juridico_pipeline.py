"""Testes do pipeline do agente jurídico (com mocks)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from classificacao_procons.juridico import pipeline as juridico_pipeline
from classificacao_procons.juridico.casos import CaseSyncResult
from classificacao_procons.juridico.events import (
    EVENT_ATUALIZAR_CONTINGENCIA,
    EVENT_ELABORAR_PECA,
    list_events,
)
from classificacao_procons.juridico.models import (
    CaseCommunication,
    CaseMovement,
    JudicialNotificationEmail,
)
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
    audiencia_registration: MondayRegistrationResult | None = None,
    communications: list | None = None,
    case_sync_result: CaseSyncResult | None = None,
    sync_calls: list | None = None,
) -> list[dict]:
    register_calls: list[dict] = []

    def fake_register(**kwargs):
        register_calls.append(kwargs)
        if isinstance(registration, Exception):
            raise registration
        return registration

    def fake_sync(**kwargs):
        if sync_calls is not None:
            sync_calls.append(kwargs)
        return case_sync_result or CaseSyncResult()

    monkeypatch.setattr(juridico_pipeline, "has_valid_token", lambda token_path: True)
    monkeypatch.setattr(juridico_pipeline, "has_gmail_modify_access", lambda token_path: True)
    monkeypatch.setattr(
        juridico_pipeline,
        "GmailJuridicoFetcher",
        SimpleNamespace(from_credentials=lambda **kwargs: fetcher),
    )
    monkeypatch.setattr(juridico_pipeline, "register_providencia", fake_register)
    monkeypatch.setattr(
        juridico_pipeline,
        "register_audiencia",
        lambda **kwargs: audiencia_registration,
    )
    monkeypatch.setattr(juridico_pipeline, "sync_case_boards", fake_sync)
    monkeypatch.setattr(juridico_pipeline, "get_api_key_from_env", lambda: None)
    monkeypatch.setattr(
        juridico_pipeline,
        "fetch_case_communications",
        lambda process_number, *, limit=5: communications or [],
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
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

        assert result.analysis != ""
        assert result.analysis_source == "heuristica"

        assert len(register_calls) == 1
        assert register_calls[0]["analysis"] == result.analysis
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

    def test_should_register_stage_specific_providencia_when_email_is_superseded(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        """Caso real: push de citação de processo que já tem acordo homologado.

        Em vez de rebaixar para ciência, o agente cadastra a providência do
        estágio atual (acompanhar o acordo) com prazo no Monday.
        """
        fetcher = FakeFetcher([_notification()])
        registration = MondayRegistrationResult(
            item_id="801",
            board_id="123",
            item_url="https://empresa.monday.com/boards/123/pulses/801",
        )
        register_calls = _patch_pipeline(monkeypatch, fetcher, registration=registration)
        monkeypatch.setattr(juridico_pipeline, "get_api_key_from_env", lambda: "chave")
        monkeypatch.setattr(
            juridico_pipeline,
            "fetch_case_movements",
            lambda process_number, *, limit=5: [
                CaseMovement(
                    movement_name="Homologação de Transação",
                    movement_code=466,
                    movement_datetime=datetime(2026, 6, 20, 15, 2, tzinfo=UTC),
                ),
            ],
        )

        results = process_new_intimacoes(options)
        result = results[0]

        assert result.status == "success"
        assert result.action_type == "cumprir_acordo"
        assert result.requires_action is True
        assert result.due_date is not None  # data de acompanhamento
        assert result.stage_note is not None
        assert "Homologação de Transação" in result.stage_note
        assert result.stage_note in result.analysis
        assert result.monday_item_url == "https://empresa.monday.com/boards/123/pulses/801"

        # cria item de prazo com a providência específica; peça não é exigida
        assert len(register_calls) == 1
        assert register_calls[0]["providencia"].action_type == "cumprir_acordo"
        events = list_events(events_path=options.events_path)
        assert [event.event_type for event in events] == [EVENT_ATUALIZAR_CONTINGENCIA]

    def test_should_consult_datajud_and_reclassify_on_dry_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        """O dry-run agora é ciente do estágio: consulta o DataJud (só leitura)."""
        fetcher = FakeFetcher([_notification()])
        register_calls = _patch_pipeline(monkeypatch, fetcher, registration=None)
        monkeypatch.setattr(juridico_pipeline, "get_api_key_from_env", lambda: "chave")
        monkeypatch.setattr(
            juridico_pipeline,
            "fetch_case_movements",
            lambda process_number, *, limit=5: [
                CaseMovement(
                    movement_name="Homologação de Transação",
                    movement_datetime=datetime(2026, 6, 20, 15, 2, tzinfo=UTC),
                ),
            ],
        )

        dry_options = JuridicoPipelineOptions(
            state_path=options.state_path,
            events_path=options.events_path,
            dry_run=True,
        )
        results = process_new_intimacoes(dry_options)
        result = results[0]

        assert result.status == "dry_run"
        assert result.action_type == "cumprir_acordo"
        assert result.stage_note is not None
        assert register_calls == []
        assert fetcher.marked_read == []
        assert not options.state_path.exists()
        assert not options.events_path.exists()

    def test_should_flag_result_when_prazo_item_was_deduplicated(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        fetcher = FakeFetcher([_notification()])
        registration = MondayRegistrationResult(
            item_id="777",
            board_id="123",
            item_url="https://empresa.monday.com/boards/123/pulses/777",
            skipped_duplicate=True,
        )
        _patch_pipeline(monkeypatch, fetcher, registration=registration)

        results = process_new_intimacoes(options)

        assert results[0].status == "success"
        assert results[0].monday_prazo_skipped_duplicate is True
        assert results[0].monday_item_url == "https://empresa.monday.com/boards/123/pulses/777"

    def test_should_sync_case_boards_with_stage_and_registrations(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        """A engrenagem dos quadros-mestre recebe o marco e os itens criados."""
        fetcher = FakeFetcher([_notification()])
        registration = MondayRegistrationResult(
            item_id="777",
            board_id="123",
            item_url="https://empresa.monday.com/boards/123/pulses/777",
        )
        sync_calls: list[dict] = []
        sync_result = CaseSyncResult()
        sync_result.actions.append("item de prazo conectado ao caso")
        _patch_pipeline(
            monkeypatch,
            fetcher,
            registration=registration,
            case_sync_result=sync_result,
            sync_calls=sync_calls,
        )
        monkeypatch.setattr(juridico_pipeline, "get_api_key_from_env", lambda: "chave")
        monkeypatch.setattr(
            juridico_pipeline,
            "fetch_case_movements",
            lambda process_number, *, limit=5: [
                CaseMovement(
                    movement_name="Homologação de Transação",
                    movement_datetime=datetime(2026, 6, 20, 15, 2, tzinfo=UTC),
                ),
            ],
        )

        results = process_new_intimacoes(options)

        assert results[0].case_sync_note == "item de prazo conectado ao caso"
        assert len(sync_calls) == 1
        call = sync_calls[0]
        assert call["stage"] == "acordo"
        assert call["stage_marker_date"] is not None
        assert call["prazo_item_id"] == "777"
        assert call["prazo_board_id"] == "123"
        assert call["audiencia_item_id"] is None

    def test_should_not_sync_case_boards_on_dry_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        fetcher = FakeFetcher([_notification()])
        sync_calls: list[dict] = []
        _patch_pipeline(monkeypatch, fetcher, registration=None, sync_calls=sync_calls)

        dry_options = JuridicoPipelineOptions(
            state_path=options.state_path,
            events_path=options.events_path,
            dry_run=True,
        )
        process_new_intimacoes(dry_options)

        assert sync_calls == []

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
        assert results[0].monday_error == "prazos: board não encontrado"
        assert results[0].monday_item_url is None
        assert len(list_events(events_path=options.events_path)) == 2

    def test_should_flag_for_review_when_process_number_is_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        """Ex.: encaminhamentos do PROJUDI sem número CNJ no corpo do e-mail."""
        fetcher = FakeFetcher(
            [
                _notification(
                    body="Informamos que há uma nova intimação. Acesse o sistema PROJUDI.",
                    subject="ENC: [PROJUDI] Informação de intimação/citação",
                ),
            ],
        )
        _patch_pipeline(monkeypatch, fetcher, registration=None)

        results = process_new_intimacoes(options)

        assert results[0].status == "needs_review"
        assert results[0].requires_action is True
        assert "[PROJUDI]" in results[0].summary
        assert results[0].error is not None
        assert "Número de processo" in results[0].error
        # continua não lido e fora do estado — reaparece até alguém tratar
        assert fetcher.marked_read == []
        assert not options.state_path.exists()

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

    def test_should_enrich_forwarded_email_with_official_communication(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        """E-mail encaminhado sem detalhes; o teor do Domicílio Judicial define a triagem."""
        forwarded = _notification(
            body=(
                "---------- Forwarded message ----------\n"
                "De: PJe TJSP <naoresponda@tjsp.jus.br>\n\n"
                "Nova comunicação no processo 1001234-56.2026.8.26.0100."
            ),
            subject="Fwd: Intimação eletrônica",
        )
        communication = CaseCommunication(
            text=(
                "CITAÇÃO da parte ré para apresentar contestação no prazo de "
                "15 (quinze) dias úteis, na 4ª Vara Cível de São Paulo. "
                "Audiência de conciliação designada para o dia 05/08/2026 às 14:30."
            ),
            communication_type="Citação",
            tribunal="TJSP",
        )
        audiencia_registration = MondayRegistrationResult(
            item_id="888",
            board_id="456",
            item_url="https://empresa.monday.com/boards/456/pulses/888",
        )
        _patch_pipeline(
            monkeypatch,
            FakeFetcher([forwarded]),
            registration=None,
            audiencia_registration=audiencia_registration,
            communications=[communication],
        )

        results = process_new_intimacoes(options)
        result = results[0]

        assert result.status == "success"
        assert result.notification_type == "citacao"
        assert result.action_type == "contestar"
        assert result.due_date is not None
        assert result.due_date.isoformat() == "2026-08-07"
        assert result.communications_count == 1
        assert "Vara Civel de Sao Paulo" in (result.court_unit or "")
        # audiência no teor → item também no board "audiências"
        assert result.hearing_datetime is not None
        assert result.monday_audiencia_url == "https://empresa.monday.com/boards/456/pulses/888"

    def test_should_tolerate_comunica_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        from classificacao_procons.juridico.comunica import ComunicaError

        fetcher = FakeFetcher([_notification()])
        _patch_pipeline(monkeypatch, fetcher, registration=None)

        def broken_fetch(process_number, *, limit=5):
            raise ComunicaError("Comunica indisponível: timeout")

        monkeypatch.setattr(juridico_pipeline, "fetch_case_communications", broken_fetch)

        results = process_new_intimacoes(options)

        assert results[0].status == "success"
        assert results[0].error is not None
        assert "Comunica indisponível" in results[0].error
        assert results[0].action_type == "contestar"

    def test_should_raise_when_google_token_is_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: JuridicoPipelineOptions,
    ) -> None:
        monkeypatch.setattr(juridico_pipeline, "has_valid_token", lambda token_path: False)
        with pytest.raises(JuridicoPipelineError, match="Google não conectado"):
            process_new_intimacoes(options)
