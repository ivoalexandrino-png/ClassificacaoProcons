"""Testes do parser de intimações judiciais."""

from datetime import date, datetime

import pytest

from classificacao_procons.juridico.models import (
    NOTIFICATION_TYPE_AUDIENCIA,
    NOTIFICATION_TYPE_CITACAO,
    NOTIFICATION_TYPE_DECISAO,
    NOTIFICATION_TYPE_INTIMACAO,
    NOTIFICATION_TYPE_SENTENCA,
)
from classificacao_procons.juridico.parser import (
    IntimacaoParseError,
    is_judicial_notification,
    parse_judicial_notification_body,
)

PJE_INTIMACAO_TEXT = """
Poder Judiciário do Estado de São Paulo
1ª Vara Cível do Foro Central da Comarca de São Paulo

Processo nº 1001234-56.2026.8.26.0100
Classe: Procedimento Comum Cível

Fica a parte ré INTIMADA da decisão proferida nos autos, devendo apresentar
manifestação no prazo de 15 (quinze) dias úteis.
"""

CITACAO_TEXT = """
JUSTIÇA DO TRABALHO — 2ª Vara do Trabalho de São Paulo
Processo 0001234-56.2026.5.02.0011

CITAÇÃO da empresa ré para apresentar defesa no prazo de 15 dias.
"""

AUDIENCIA_HTML = """
<html><body>
<p>Processo nº 1001234-56.2026.8.26.0100</p>
<p>Audiência de conciliação designada para o dia 05/08/2026 às 14:30,
na 3ª Vara Cível de São Paulo.</p>
</body></html>
"""


class TestIsJudicialNotification:
    def test_should_match_when_sender_is_jus_br(self) -> None:
        assert is_judicial_notification(
            subject="Qualquer assunto",
            sender="PJe TJSP <naoresponda@tjsp.jus.br>",
        )

    def test_should_match_when_subject_has_push_keyword(self) -> None:
        assert is_judicial_notification(
            subject="Push: nova movimentação processual",
            sender="alertas@servicopush.com.br",
        )

    def test_should_match_when_subject_has_intimacao_with_accents(self) -> None:
        assert is_judicial_notification(
            subject="Intimação eletrônica — processo em andamento",
            sender="alguem@example.com",
        )

    def test_should_not_match_when_sender_and_subject_are_unrelated(self) -> None:
        assert not is_judicial_notification(
            subject="Promoção imperdível",
            sender="marketing@loja.com.br",
        )


class TestParseJudicialNotificationBody:
    def test_should_parse_intimacao_with_deadline_in_business_days(self) -> None:
        result = parse_judicial_notification_body(text=PJE_INTIMACAO_TEXT)

        assert result.process_number == "1001234-56.2026.8.26.0100"
        assert result.notification_type == NOTIFICATION_TYPE_DECISAO
        assert result.tribunal == "TJSP"
        assert result.court_unit is not None
        assert "Vara Civel do Foro Central" in result.court_unit
        assert result.deadline_days == 15
        assert result.deadline_in_business_days is True
        assert result.hearing_datetime is None

    def test_should_parse_citacao_from_labor_court(self) -> None:
        result = parse_judicial_notification_body(text=CITACAO_TEXT)

        assert result.process_number == "0001234-56.2026.5.02.0011"
        assert result.notification_type == NOTIFICATION_TYPE_CITACAO
        assert result.tribunal == "TRT2"
        assert result.deadline_days == 15

    def test_should_parse_hearing_date_and_time_from_html(self) -> None:
        result = parse_judicial_notification_body(html=AUDIENCIA_HTML)

        assert result.notification_type == NOTIFICATION_TYPE_AUDIENCIA
        assert result.hearing_datetime == datetime(2026, 8, 5, 14, 30)

    def test_should_parse_explicit_deadline_date(self) -> None:
        text = (
            "Processo 1001234-56.2026.8.26.0100. Intimação: prazo fatal em 20/08/2026 "
            "para manifestação."
        )
        result = parse_judicial_notification_body(text=text)
        assert result.deadline_date == date(2026, 8, 20)

    def test_should_flag_calendar_days_when_prazo_corrido(self) -> None:
        text = "Processo 1001234-56.2026.8.26.0100. Prazo de 10 dias corridos."
        result = parse_judicial_notification_body(text=text)
        assert result.deadline_days == 10
        assert result.deadline_in_business_days is False

    def test_should_detect_sentenca(self) -> None:
        text = "Processo 1001234-56.2026.8.26.0100. Publicada a sentença nos autos."
        result = parse_judicial_notification_body(text=text)
        assert result.notification_type == NOTIFICATION_TYPE_SENTENCA

    def test_should_default_to_intimacao_when_type_is_unclear(self) -> None:
        text = "Processo 1001234-56.2026.8.26.0100. Juntada de petição."
        result = parse_judicial_notification_body(text=text)
        assert result.notification_type == NOTIFICATION_TYPE_INTIMACAO

    def test_should_use_subject_when_body_lacks_process_number(self) -> None:
        result = parse_judicial_notification_body(
            text="Nova movimentação disponível no sistema.",
            subject="Push processo 1001234-56.2026.8.26.0100",
        )
        assert result.process_number == "1001234-56.2026.8.26.0100"

    def test_should_raise_when_body_is_empty(self) -> None:
        with pytest.raises(IntimacaoParseError, match="Corpo do e-mail vazio"):
            parse_judicial_notification_body()

    def test_should_raise_when_process_number_is_missing(self) -> None:
        with pytest.raises(IntimacaoParseError, match="Número de processo"):
            parse_judicial_notification_body(text="Intimação sem número nenhum.")

    def test_should_truncate_long_summary(self) -> None:
        text = "Processo 1001234-56.2026.8.26.0100. " + "conteúdo " * 200
        result = parse_judicial_notification_body(text=text)
        assert len(result.summary) <= 600
