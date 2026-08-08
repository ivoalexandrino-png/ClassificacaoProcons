"""Testes das heurísticas de extração de texto do Questor (sem navegador)."""

from datetime import date

from classificacao_procons.questor.portal import parse_certidoes_lines


def test_parse_certidoes_lines_should_extract_status_and_dates() -> None:
    lines = [
        "Certidões negativas",
        "Receita Federal / PGFN    Negativa    10/07/2026    07/01/2027",
        "FGTS - CRF    Positiva    05/08/2026",
        "Municipal - ISS    Indisponível",
        "Rodapé qualquer sem situação",
    ]
    certidoes = parse_certidoes_lines(lines, cnpj="12.345.678/0001-99")
    assert len(certidoes) == 3

    federal = certidoes[0]
    assert federal.orgao == "Receita Federal / PGFN"
    assert federal.situacao == "negativa"
    assert federal.data_emissao == date(2026, 7, 10)
    assert federal.data_validade == date(2027, 1, 7)
    assert federal.cnpj == "12345678000199"

    assert certidoes[1].situacao == "positiva"
    assert certidoes[2].situacao == "indisponivel"


def test_parse_certidoes_lines_should_skip_lines_without_status() -> None:
    assert parse_certidoes_lines(["apenas um cabeçalho", "outra linha"]) == []
