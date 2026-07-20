"""Testes do parser de e-mail Uberlândia."""

from datetime import date

import pytest

from classificacao_procons.uberlandia.email_parser import (
    UBERLANDIA_SENDER,
    UberlandiaEmailParseError,
    extract_uberlandia_protocol_number,
    is_uberlandia_notification,
    parse_uberlandia_notification_body,
)

REAL_EMAIL_TEXT = """
Acompanhe o processo 2026.02.0399.008.51708 pelo site https://faleprocon.uberlandia.mg.gov.br/empresas
1ª Notificação Eletrônica 06/03/2026
Consumidores
Nome e Documento: Danielle cardoso van eyken | 04408548650
Descrição
Esta reclamação, foi gerada por intermédio do site eletrônico/app faleprocon.
Relato consumidor - renovação automática sem consentimento.
Solução
Cancelamento imediato da assinatura sem cobrança de multa.
"""


class TestUberlandiaEmailParser:
    def test_should_match_notification_with_consumer_data(self) -> None:
        assert is_uberlandia_notification(
            subject="Notificação",
            sender=UBERLANDIA_SENDER,
            body=REAL_EMAIL_TEXT,
        )

    def test_should_reject_audiencia_email_without_consumer_data(self) -> None:
        body = (
            "Acompanhe o processo 2026.01.0399.008.48902 pelo site "
            "https://faleprocon.uberlandia.mg.gov.br/empresas\n"
            "Solicitação de documentos para audiência 22/04/2026"
        )
        assert not is_uberlandia_notification(
            subject="Notificação",
            sender=UBERLANDIA_SENDER,
            body=body,
        )

    def test_should_extract_protocol_number(self) -> None:
        number = extract_uberlandia_protocol_number(
            "Acompanhe o processo 2026.02.0399.008.51708 pelo site",
        )
        assert number == "2026.02.0399.008.51708"

    def test_should_parse_notification_body(self) -> None:
        parsed = parse_uberlandia_notification_body(text=REAL_EMAIL_TEXT)
        assert parsed.protocol_number == "2026.02.0399.008.51708"
        assert parsed.consumer_name == "Danielle cardoso van eyken"
        assert parsed.consumer_cpf == "04408548650"
        assert parsed.complaint_date == date(2026, 3, 6)
        assert parsed.cause is not None
        assert "renovação automática" in parsed.cause

    def test_should_raise_when_consumer_missing(self) -> None:
        with pytest.raises(UberlandiaEmailParseError, match="consumidora"):
            parse_uberlandia_notification_body(
                text="Acompanhe o processo 2026.02.0399.008.51708",
            )
