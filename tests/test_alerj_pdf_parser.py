"""Testes do parser de PDF ALERJ."""

from datetime import date

import pytest

from classificacao_procons.alerj.pdf_parser import AlerjPdfParseError, parse_alerj_pdf_text

REAL_PDF_TEXT = """
ASSEMBLEIA LEGISLATIVA DO ESTADO DO RIO DE JANEIRO
NOTIFICAÇÃO N.º 245984/2026
Objeto da reclamação: Trata-se da reclamação de nº 312133/2026, da Sra. Manuela Cadilhe
Duarte, residente a Travessa Lafaite Silva,542 - Porto Velho - São Gonçalo - RJ
CPF:135.938.527-48
A consumidora informa que há cerca de dois anos, assinou o plano anual Lambox junto à
plataforma reclamada, por aproximadamente R$ 80,00 mensais.
Solicita o cancelamento do contrato e o reembolso integral do valor debitado indevidamente.
E-mail: mauelacadilhed@hotmail.com
Reclamação com base nos artigos 2º, 3º, 12 ao 25 do CDC.
Rio de Janeiro, 12 de março de 2026
"""


class TestAlerjPdfParser:
    def test_should_parse_real_pdf_text(self) -> None:
        parsed = parse_alerj_pdf_text(REAL_PDF_TEXT)
        assert parsed.protocol_number == "312133/2026"
        assert parsed.consumer_name == "Manuela Cadilhe Duarte"
        assert parsed.consumer_cpf == "13593852748"
        assert parsed.complaint_date == date(2026, 3, 12)
        assert "plano anual Lambox" in parsed.cause
        assert "NOTIFICAÇÃO" not in parsed.cause

    def test_should_raise_when_protocol_missing(self) -> None:
        with pytest.raises(AlerjPdfParseError, match="reclamação ALERJ"):
            parse_alerj_pdf_text("PDF sem protocolo")
