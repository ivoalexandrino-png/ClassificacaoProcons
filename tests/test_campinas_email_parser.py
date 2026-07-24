"""Testes do parser de e-mail Procon Campinas."""

from datetime import date

import pytest

from classificacao_procons.campinas.email_parser import (
    CAMPINAS_SENDER,
    CampinasEmailParseError,
    extract_campinas_protocol_number,
    is_campinas_notification,
    parse_campinas_notification_body,
)

CAMPINAS_HTML = """
<p>Notificação de CIP</p>
<p>CIP nº 12345/2026/CIP</p>
<p>Nome: MARIA DA SILVA</p>
<p>CPF: 123.456.789-01</p>
<p>Data: 10/07/2026</p>
"""


class TestCampinasEmailParser:
    def test_should_match_campinas_notification(self) -> None:
        assert is_campinas_notification(
            subject="Notificação CIP",
            sender=CAMPINAS_SENDER,
        )

    def test_should_reject_non_campinas_sender(self) -> None:
        assert not is_campinas_notification(
            subject="Notificação CIP",
            sender="outro@example.com",
        )

    def test_should_extract_protocol_number(self) -> None:
        number = extract_campinas_protocol_number("CIP nº 98765/2025/CIP")
        assert number == "98765/2025"

    def test_should_parse_notification_body(self) -> None:
        parsed = parse_campinas_notification_body(html=CAMPINAS_HTML)
        assert parsed.protocol_number == "12345/2026"
        assert parsed.consumer_name == "MARIA DA SILVA"
        assert parsed.consumer_cpf == "12345678901"
        assert parsed.complaint_date == date(2026, 7, 10)

    def test_should_raise_when_protocol_number_missing(self) -> None:
        with pytest.raises(CampinasEmailParseError, match="Número da CIP"):
            parse_campinas_notification_body(html="<p>Sem número</p>")
