"""Testes do parser de e-mail Proconsumidor."""

import pytest

from classificacao_procons.proconsumidor.email_parser import (
    PROCONSUMIDOR_SENDER,
    PROCONSUMIDOR_SUBJECT,
    ProconsumidorEmailParseError,
    extract_proconsumidor_complaint_number,
    extract_proconsumidor_state,
    is_proconsumidor_notification,
    parse_proconsumidor_notification_body,
)

PROCONSUMIDOR_HTML = """
<p>Proconsumidor - Notificação</p>
<p>Há uma nova notificação relativa à reclamação
<strong>26.05.0627.001.00161-302</strong> do
<strong>Procon Regional de Leste de Minas - CIMDOCE - MG</strong>.</p>
<p>Para mais detalhes, acesse www.proconsumidor.mj.gov.br.</p>
"""


class TestProconsumidorEmailParser:
    def test_should_match_proconsumidor_notification(self) -> None:
        assert is_proconsumidor_notification(
            subject=PROCONSUMIDOR_SUBJECT,
            sender=PROCONSUMIDOR_SENDER,
        )

    def test_should_extract_complaint_number(self) -> None:
        number = extract_proconsumidor_complaint_number(
            "reclamação 26.05.0627.001.00161-302 do Procon Regional",
        )
        assert number == "26.05.0627.001.00161-302"

    def test_should_extract_state_from_regional_org(self) -> None:
        assert (
            extract_proconsumidor_state("Procon Regional de Leste de Minas - CIMDOCE - MG")
            == "MG"
        )

    def test_should_parse_notification_body(self) -> None:
        parsed = parse_proconsumidor_notification_body(html=PROCONSUMIDOR_HTML)
        assert parsed.complaint_number == "26.05.0627.001.00161-302"
        assert parsed.regional_org is not None
        assert "CIMDOCE" in parsed.regional_org
        assert parsed.state == "MG"

    def test_should_raise_when_complaint_number_missing(self) -> None:
        with pytest.raises(ProconsumidorEmailParseError, match="Número da reclamação"):
            parse_proconsumidor_notification_body(html="<p>Sem número</p>")

    def test_should_match_carta_notification_subject(self) -> None:
        assert is_proconsumidor_notification(
            subject="Notificação de Carta",
            sender=PROCONSUMIDOR_SENDER,
        )

    def test_should_parse_carta_notification_body(self) -> None:
        parsed = parse_proconsumidor_notification_body(
            text=(
                "Foi emitida uma carta relativa à reclamação "
                "26.07.0158.011.00300-301 pelo Procon do Distrito Federal - DF."
            ),
        )
        assert parsed.complaint_number == "26.07.0158.011.00300-301"
        assert parsed.regional_org == "Procon do Distrito Federal - DF"
        assert parsed.state == "DF"
