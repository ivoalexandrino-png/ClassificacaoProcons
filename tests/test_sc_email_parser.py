"""Testes do parser de e-mail SC/SSP."""

import pytest

from classificacao_procons.sc.email_parser import (
    SC_ORIGINAL_SENDER,
    ScEmailParseError,
    extract_ssp_protocol_number,
    is_sc_ssp_notification,
    parse_sc_ssp_notification,
)

REAL_FORWARDED_BODY = """
---------- Forwarded message ---------
De: PROTOCOLO CARTORIO <protocolocartorio@procon.sc.gov.br>
Date: seg., 20 de jul. de 2026 às 09:56
Subject: Processo SSP 00027157/2026
To: <financeiro@b4a.com.br>

Prezado(a) Senhor(a),

Em referência à Carta de Informações Preliminares (CIP) anexa, informamos
que é necessário que a manifestação seja feita neste email.
O prazo máximo para resposta é de 20 dias úteis a contar do recebimento deste.
"""


class TestScSspEmailParser:
    def test_should_match_forwarded_ssp_email(self) -> None:
        assert is_sc_ssp_notification(
            subject="Fwd: Processo SSP 00027157/2026",
            sender="lorrany.dumont@b4a.ai",
            body=REAL_FORWARDED_BODY,
        )

    def test_should_match_direct_procon_sender(self) -> None:
        assert is_sc_ssp_notification(
            subject="Processo SSP 00027157/2026",
            sender=SC_ORIGINAL_SENDER,
            body="",
        )

    def test_should_reject_unrelated_subject(self) -> None:
        assert not is_sc_ssp_notification(
            subject="Reunião semanal",
            sender="outro@example.com",
            body="",
        )

    def test_should_extract_protocol_number(self) -> None:
        assert extract_ssp_protocol_number("Fwd: Processo SSP 00027157/2026") == "00027157/2026"

    def test_should_parse_forwarded_notification(self) -> None:
        parsed = parse_sc_ssp_notification(
            subject="Fwd: Processo SSP 00027157/2026",
            text=REAL_FORWARDED_BODY,
        )
        assert parsed.protocol_number == "00027157/2026"

    def test_should_raise_when_protocol_missing(self) -> None:
        with pytest.raises(ScEmailParseError, match="processo SSP"):
            parse_sc_ssp_notification(subject="Notificação genérica", text="sem número")
