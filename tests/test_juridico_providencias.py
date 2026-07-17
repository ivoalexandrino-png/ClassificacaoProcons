"""Testes da triagem de providências."""

from datetime import date, datetime

from classificacao_procons.juridico.models import (
    ACTION_ANALISAR_RECURSO,
    ACTION_COMPARECER_AUDIENCIA,
    ACTION_CONTESTAR,
    ACTION_MANIFESTAR,
    ACTION_TOMAR_CIENCIA,
    NOTIFICATION_TYPE_AUDIENCIA,
    NOTIFICATION_TYPE_CITACAO,
    NOTIFICATION_TYPE_DECISAO,
    NOTIFICATION_TYPE_INTIMACAO,
    NOTIFICATION_TYPE_SENTENCA,
    ParsedIntimacao,
)
from classificacao_procons.juridico.providencias import affects_contingency, classify_providencia

BASE_DATE = date(2026, 7, 17)  # sexta-feira


def _intimacao(**overrides: object) -> ParsedIntimacao:
    defaults: dict[str, object] = {
        "process_number": "1001234-56.2026.8.26.0100",
        "notification_type": NOTIFICATION_TYPE_INTIMACAO,
        "summary": "",
    }
    defaults.update(overrides)
    return ParsedIntimacao(**defaults)  # type: ignore[arg-type]


class TestClassifyProvidencia:
    def test_should_require_contestacao_with_default_deadline_when_citacao(self) -> None:
        result = classify_providencia(
            _intimacao(notification_type=NOTIFICATION_TYPE_CITACAO),
            base_date=BASE_DATE,
        )
        assert result.action_type == ACTION_CONTESTAR
        assert result.requires_action is True
        assert result.requires_legal_document is True
        assert result.due_date == date(2026, 8, 7)  # 15 dias úteis

    def test_should_use_extracted_deadline_when_present(self) -> None:
        result = classify_providencia(
            _intimacao(notification_type=NOTIFICATION_TYPE_CITACAO, deadline_days=5),
            base_date=BASE_DATE,
        )
        assert result.due_date == date(2026, 7, 24)  # 5 dias úteis

    def test_should_schedule_hearing_when_audiencia(self) -> None:
        hearing = datetime(2026, 8, 5, 14, 30)
        result = classify_providencia(
            _intimacao(
                notification_type=NOTIFICATION_TYPE_AUDIENCIA,
                hearing_datetime=hearing,
            ),
            base_date=BASE_DATE,
        )
        assert result.action_type == ACTION_COMPARECER_AUDIENCIA
        assert result.hearing_datetime == hearing
        assert result.due_date == date(2026, 8, 5)
        assert result.requires_legal_document is False

    def test_should_keep_contestacao_when_citacao_also_schedules_hearing(self) -> None:
        hearing = datetime(2026, 8, 5, 14, 30)
        result = classify_providencia(
            _intimacao(
                notification_type=NOTIFICATION_TYPE_CITACAO,
                deadline_days=15,
                hearing_datetime=hearing,
            ),
            base_date=BASE_DATE,
        )
        assert result.action_type == ACTION_CONTESTAR
        assert result.requires_legal_document is True
        assert result.hearing_datetime == hearing
        assert result.due_date == date(2026, 8, 7)

    def test_should_analyze_appeal_when_sentenca(self) -> None:
        result = classify_providencia(
            _intimacao(notification_type=NOTIFICATION_TYPE_SENTENCA),
            base_date=BASE_DATE,
        )
        assert result.action_type == ACTION_ANALISAR_RECURSO
        assert result.requires_legal_document is True
        assert result.due_date == date(2026, 8, 7)

    def test_should_request_manifestacao_when_decisao_asks_for_it(self) -> None:
        result = classify_providencia(
            _intimacao(
                notification_type=NOTIFICATION_TYPE_DECISAO,
                summary="Intime-se a ré para manifestação sobre os documentos.",
            ),
            base_date=BASE_DATE,
        )
        assert result.action_type == ACTION_MANIFESTAR
        assert result.due_date == date(2026, 7, 24)  # default 5 dias úteis

    def test_should_only_acknowledge_when_no_action_needed(self) -> None:
        result = classify_providencia(
            _intimacao(summary="Processo arquivado definitivamente."),
            base_date=BASE_DATE,
        )
        assert result.action_type == ACTION_TOMAR_CIENCIA
        assert result.requires_action is False
        assert result.due_date is None

    def test_should_prefer_explicit_deadline_date(self) -> None:
        result = classify_providencia(
            _intimacao(
                notification_type=NOTIFICATION_TYPE_CITACAO,
                deadline_date=date(2026, 9, 1),
            ),
            base_date=BASE_DATE,
        )
        assert result.due_date == date(2026, 9, 1)

    def test_should_flag_contingency_when_summary_mentions_deposito(self) -> None:
        result = classify_providencia(
            _intimacao(summary="Intimação sobre depósito judicial efetuado nos autos."),
            base_date=BASE_DATE,
        )
        assert result.affects_contingency is True

    def test_should_treat_generic_intimacao_with_deadline_as_manifestacao(self) -> None:
        result = classify_providencia(
            _intimacao(deadline_days=10),
            base_date=BASE_DATE,
        )
        assert result.action_type == ACTION_MANIFESTAR
        assert result.due_date == date(2026, 7, 31)  # 10 dias úteis


class TestAffectsContingency:
    def test_should_detect_penhora(self) -> None:
        assert affects_contingency("Determinada a penhora via SISBAJUD.") is True

    def test_should_detect_accented_keyword(self) -> None:
        assert affects_contingency("Expedido alvará de levantamento.") is True

    def test_should_return_false_for_neutral_text(self) -> None:
        assert affects_contingency("Juntada de procuração aos autos.") is False

    def test_should_return_false_for_empty_text(self) -> None:
        assert affects_contingency("") is False
