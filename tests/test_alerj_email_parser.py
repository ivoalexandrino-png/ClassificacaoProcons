"""Testes do parser de e-mail ALERJ."""

import pytest

from classificacao_procons.alerj.email_parser import (
    ALERJ_ORIGINAL_SENDER,
    AlerjEmailParseError,
    extract_alerj_protocol_number,
    is_alerj_notification,
    parse_alerj_notification,
)

REAL_FORWARDED_BODY = """
---------- Forwarded message ---------
De: Fátima Penha de Azevedo Vasques Ferreira <FFERREIRA@alerj.rj.gov.br>
Date: qui., 12 de mar. de 2026 às 17:14
Subject: NOTIFICAÇÃO N.º 245984/2026
To: financeiro@b4a.com.br
Cc: Defesa do Consumidor <defesadoconsumidor@alerj.rj.gov.br>

Sigo no envio do presente para informar o recebimento por mim, conciliadora
do órgão, do procedimento número *312133*/2026.

Solicito que o envio da resposta seja encaminhada para o endereço eletrônico
fferreira@alerj.rj.gov.br com cópia para defesadoconsumidor@alerj.rj.gov.br.
"""


class TestAlerjEmailParser:
    def test_should_match_forwarded_alerj_email(self) -> None:
        assert is_alerj_notification(
            subject="Fwd: NOTIFICAÇÃO N.º 245984/2026",
            sender="vanessa.barajas@b4a.com.br",
            body=REAL_FORWARDED_BODY,
        )

    def test_should_match_direct_alerj_sender(self) -> None:
        assert is_alerj_notification(
            subject="NOTIFICAÇÃO N.º 245984/2026",
            sender=ALERJ_ORIGINAL_SENDER,
            body="procedimento número 312133/2026",
        )

    def test_should_reject_unrelated_subject(self) -> None:
        assert not is_alerj_notification(
            subject="Reunião semanal",
            sender="outro@example.com",
            body="",
        )

    def test_should_extract_protocol_number(self) -> None:
        assert (
            extract_alerj_protocol_number(
                "procedimento número *312133*/2026",
            )
            == "312133/2026"
        )

    def test_should_parse_forwarded_notification(self) -> None:
        parsed = parse_alerj_notification(
            subject="Fwd: NOTIFICAÇÃO N.º 245984/2026",
            text=REAL_FORWARDED_BODY,
        )
        assert parsed.protocol_number == "312133/2026"
        assert parsed.notification_number == "245984/2026"

    def test_should_raise_when_protocol_missing(self) -> None:
        with pytest.raises(AlerjEmailParseError, match="procedimento ALERJ"):
            parse_alerj_notification(
                subject="Fwd: NOTIFICAÇÃO N.º 245984/2026",
                text="sem número de procedimento",
            )
