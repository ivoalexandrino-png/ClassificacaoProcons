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
    CaseMovement,
    ParsedIntimacao,
    Providencia,
)
from classificacao_procons.juridico.providencias import (
    affects_contingency,
    classify_providencia,
    downgrade_providencia_for_stage,
)

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


def _providencia_contestar() -> Providencia:
    return Providencia(
        action_type=ACTION_CONTESTAR,
        description="Apresentar contestação",
        requires_action=True,
        due_date=date(2026, 8, 7),
        requires_legal_document=True,
    )


class TestDowngradeProvidenciaForStage:
    def test_should_downgrade_contestar_when_acordo_homologado_in_movements(self) -> None:
        # Caso real 0001206-20.2026.8.16.0195: push de citação chegou depois
        # de o processo já ter contestação, acordo homologado e sentença.
        movements = [
            CaseMovement(
                movement_name="Homologação de Transação",
                movement_code=466,
                movement_datetime=datetime(2026, 6, 20, 15, 2),
            ),
        ]
        result = downgrade_providencia_for_stage(_providencia_contestar(), movements)

        assert result.action_type == ACTION_TOMAR_CIENCIA
        assert result.requires_action is False
        assert result.requires_legal_document is False
        assert result.due_date is None
        assert result.stage_note is not None
        assert "Homologação de Transação" in result.stage_note
        assert "20/06/2026" in result.stage_note

    def test_should_downgrade_contestar_when_contestacao_already_filed(self) -> None:
        movements = [CaseMovement(movement_name="Juntada de Contestação")]
        result = downgrade_providencia_for_stage(_providencia_contestar(), movements)
        assert result.action_type == ACTION_TOMAR_CIENCIA
        assert result.stage_note is not None
        assert "data não informada" in result.stage_note

    def test_should_downgrade_contestar_when_sentenca_exists(self) -> None:
        movements = [CaseMovement(movement_name="Sentença de Procedência em Parte")]
        result = downgrade_providencia_for_stage(_providencia_contestar(), movements)
        assert result.action_type == ACTION_TOMAR_CIENCIA

    def test_should_keep_contestar_when_movements_do_not_supersede(self) -> None:
        movements = [
            CaseMovement(movement_name="Distribuição"),
            CaseMovement(movement_name="Expedição de documento"),
            CaseMovement(movement_name="Petição"),
        ]
        result = downgrade_providencia_for_stage(_providencia_contestar(), movements)
        assert result == _providencia_contestar()

    def test_should_keep_providencia_when_there_are_no_movements(self) -> None:
        result = downgrade_providencia_for_stage(_providencia_contestar(), [])
        assert result == _providencia_contestar()

    def test_should_downgrade_recurso_when_transito_em_julgado(self) -> None:
        providencia = Providencia(
            action_type=ACTION_ANALISAR_RECURSO,
            description="Analisar sentença e avaliar recurso",
            requires_action=True,
            due_date=date(2026, 8, 5),
            requires_legal_document=True,
        )
        movements = [CaseMovement(movement_name="Trânsito em Julgado")]
        result = downgrade_providencia_for_stage(providencia, movements)
        assert result.action_type == ACTION_TOMAR_CIENCIA

    def test_should_not_downgrade_recurso_because_of_sentenca(self) -> None:
        # A sentença é justamente o gatilho do recurso — não pode rebaixar.
        providencia = Providencia(
            action_type=ACTION_ANALISAR_RECURSO,
            description="Analisar sentença e avaliar recurso",
            requires_action=True,
            due_date=date(2026, 8, 5),
        )
        movements = [CaseMovement(movement_name="Sentença de Improcedência")]
        assert downgrade_providencia_for_stage(providencia, movements) == providencia

    def test_should_downgrade_manifestar_when_arquivamento(self) -> None:
        providencia = Providencia(
            action_type=ACTION_MANIFESTAR,
            description="Apresentar manifestação",
            requires_action=True,
            due_date=date(2026, 7, 24),
        )
        movements = [CaseMovement(movement_name="Arquivamento Definitivo")]
        result = downgrade_providencia_for_stage(providencia, movements)
        assert result.action_type == ACTION_TOMAR_CIENCIA

    def test_should_keep_tomar_ciencia_unchanged(self) -> None:
        providencia = Providencia(
            action_type=ACTION_TOMAR_CIENCIA,
            description="Tomar ciência do andamento",
            requires_action=False,
        )
        movements = [CaseMovement(movement_name="Sentença")]
        assert downgrade_providencia_for_stage(providencia, movements) == providencia

    def test_should_preserve_hearing_and_contingency_flags_when_downgrading(self) -> None:
        providencia = Providencia(
            action_type=ACTION_CONTESTAR,
            description="Apresentar contestação",
            requires_action=True,
            hearing_datetime=datetime(2026, 8, 5, 14, 30),
            affects_contingency=True,
        )
        movements = [CaseMovement(movement_name="Homologação de Transação")]
        result = downgrade_providencia_for_stage(providencia, movements)
        assert result.hearing_datetime == datetime(2026, 8, 5, 14, 30)
        assert result.affects_contingency is True


class TestAffectsContingency:
    def test_should_detect_penhora(self) -> None:
        assert affects_contingency("Determinada a penhora via SISBAJUD.") is True

    def test_should_detect_accented_keyword(self) -> None:
        assert affects_contingency("Expedido alvará de levantamento.") is True

    def test_should_return_false_for_neutral_text(self) -> None:
        assert affects_contingency("Juntada de procuração aos autos.") is False

    def test_should_return_false_for_empty_text(self) -> None:
        assert affects_contingency("") is False
