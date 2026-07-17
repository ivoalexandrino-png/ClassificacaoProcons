"""Testes do parser de intimações do agente jurídico."""

from datetime import date, datetime

import pytest

from classificacao_procons.juridico.parser import (
    IntimacaoParseError,
    derive_tribunal_from_cnj,
    looks_like_intimacao,
    parse_intimacao_body,
)

_INTIMACAO_TXT = (
    "Intimação Eletrônica - Diário da Justiça Eletrônico\n"
    "Processo nº 1023456-78.2026.8.26.0100\n"
    "3ª Vara Cível do Foro Central da Comarca de São Paulo - TJSP\n"
    "Fica a parte ré intimada da sentença para apresentar recurso "
    "no prazo de 15 (quinze) dias úteis.\n"
    "Disponibilizado no DJe em 16/07/2026, considera-se publicado em 17/07/2026.\n"
    "Acesse: https://esaj.tjsp.jus.br/cpopg/open.do\n"
)


class TestLooksLikeIntimacao:
    def test_should_detect_by_cnj_number(self) -> None:
        assert looks_like_intimacao(body="Autos 1023456-78.2026.8.26.0100")

    def test_should_detect_by_keyword(self) -> None:
        assert looks_like_intimacao(subject="Intimação eletrônica", body="qualquer texto")

    def test_should_reject_unrelated_email(self) -> None:
        assert not looks_like_intimacao(subject="Promoção", body="Compre agora com desconto")


class TestParseIntimacaoBody:
    def test_should_extract_core_fields(self) -> None:
        parsed = parse_intimacao_body(text=_INTIMACAO_TXT)
        assert parsed.process_number == "1023456-78.2026.8.26.0100"
        assert parsed.tribunal == "TJSP"
        assert parsed.vara.startswith("3ª Vara Cível")
        assert parsed.movement_type == "Sentença"
        assert parsed.prazo_dias == 15
        assert parsed.prazo_uteis is True
        assert parsed.portal_url == "https://esaj.tjsp.jus.br/cpopg/open.do"

    def test_should_prefer_publication_over_availability_date(self) -> None:
        parsed = parse_intimacao_body(text=_INTIMACAO_TXT)
        assert parsed.publication_date == date(2026, 7, 17)

    def test_should_fallback_to_availability_date(self) -> None:
        text = "Processo 1023456-78.2026.8.26.0100 disponibilizado em 10/03/2026."
        parsed = parse_intimacao_body(text=text)
        assert parsed.publication_date == date(2026, 3, 10)

    def test_should_extract_process_from_20_digit_number(self) -> None:
        text = "Autos 10234567820268260100 intimação para manifestar."
        parsed = parse_intimacao_body(text=text)
        assert parsed.process_number == "1023456-78.2026.8.26.0100"

    def test_should_detect_corridos_prazo(self) -> None:
        text = "Processo 1023456-78.2026.8.26.0100, prazo de 10 dias corridos."
        parsed = parse_intimacao_body(text=text)
        assert parsed.prazo_dias == 10
        assert parsed.prazo_uteis is False

    def test_should_extract_prazo_written_as_word(self) -> None:
        text = "Processo 1023456-78.2026.8.26.0100 no prazo de quinze dias."
        parsed = parse_intimacao_body(text=text)
        assert parsed.prazo_dias == 15

    def test_should_extract_hearing_datetime(self) -> None:
        text = (
            "Processo 1023456-78.2026.8.26.0100. Audiência de conciliação "
            "designada para 15/08/2026 às 14:30."
        )
        parsed = parse_intimacao_body(text=text)
        assert parsed.hearing_at == datetime(2026, 8, 15, 14, 30)

    def test_should_parse_from_html(self) -> None:
        html = (
            "<html><body><p>Processo 1023456-78.2026.8.26.0100</p>"
            '<a href="https://pje.tjsp.jus.br/x">andamento</a>'
            "<p>prazo de 5 dias úteis</p></body></html>"
        )
        parsed = parse_intimacao_body(html=html)
        assert parsed.process_number == "1023456-78.2026.8.26.0100"
        assert parsed.prazo_dias == 5
        assert parsed.portal_url == "https://pje.tjsp.jus.br/x"

    def test_should_raise_when_no_process_number(self) -> None:
        with pytest.raises(IntimacaoParseError):
            parse_intimacao_body(text="Nenhum número de processo aqui.")

    def test_should_raise_on_empty_body(self) -> None:
        with pytest.raises(IntimacaoParseError):
            parse_intimacao_body()


class TestDeriveTribunal:
    def test_should_derive_tjsp(self) -> None:
        assert derive_tribunal_from_cnj("1023456-78.2026.8.26.0100") == "TJSP"

    def test_should_derive_tjrj(self) -> None:
        assert derive_tribunal_from_cnj("1023456-78.2026.8.19.0001") == "TJRJ"

    def test_should_derive_federal_trf(self) -> None:
        assert derive_tribunal_from_cnj("1023456-78.2026.4.03.6100") == "TRF3"

    def test_should_derive_labor_trt(self) -> None:
        assert derive_tribunal_from_cnj("1023456-78.2026.5.02.0001") == "TRT2"

    def test_should_return_none_for_invalid(self) -> None:
        assert derive_tribunal_from_cnj("nao-e-cnj") is None
