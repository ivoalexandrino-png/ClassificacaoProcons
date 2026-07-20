"""Testes do parser de PDF SC/SSP."""

from datetime import date

import pytest

from classificacao_procons.sc.pdf_parser import ScPdfParseError, parse_sc_ssp_pdf_text

REAL_PDF_TEXT = """
TERMO DE AUTUAÇÃO
Processo SSP 00027157/2026
Autuado em: 30/06/2026 às 22:07
CPF
11506495931
Nome Completo
MARIA EDUARDA DE SOUZA OSORIO
Relato da ocorrência
2
Governo do Estado de Santa Catarina
Enviar reclamação ou denúncia para o Procon
Tinha uma assinatura mensal da Glam box que vem produtos de beleza.
Pedido para a empresa
Espero que resolva o problema.
"""


class TestScSspPdfParser:
    def test_should_parse_real_pdf_text(self) -> None:
        parsed = parse_sc_ssp_pdf_text(REAL_PDF_TEXT)
        assert parsed.protocol_number == "00027157/2026"
        assert parsed.consumer_name == "MARIA EDUARDA DE SOUZA OSORIO"
        assert parsed.consumer_cpf == "11506495931"
        assert parsed.complaint_date == date(2026, 6, 30)
        assert "assinatura mensal da Glam box" in parsed.cause
        assert "Governo do Estado" not in parsed.cause

    def test_should_raise_when_protocol_missing(self) -> None:
        with pytest.raises(ScPdfParseError, match="processo SSP"):
            parse_sc_ssp_pdf_text("PDF sem protocolo")
