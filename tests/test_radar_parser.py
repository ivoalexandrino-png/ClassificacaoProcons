"""Testes de normalização/classificação do radar de editais."""

from datetime import date

from classificacao_procons.radar.parser import (
    classify_areas,
    detect_scope,
    detect_status,
    looks_like_edital,
    parse_date,
)


class TestClassifyAreas:
    def test_should_detect_direito(self) -> None:
        assert classify_areas("Edital de pesquisa em Direito Constitucional") == ("direito",)

    def test_should_detect_saude_in_english(self) -> None:
        assert classify_areas("Grant for public health research") == ("saude",)

    def test_should_detect_administracao(self) -> None:
        areas = classify_areas("Chamada em Gestão e Administração Pública")
        assert "administracao" in areas

    def test_should_detect_educacao(self) -> None:
        assert classify_areas("Bolsa para formação de professores") == ("educacao",)

    def test_should_detect_multiple_areas(self) -> None:
        areas = classify_areas("Políticas públicas de saúde e educação")
        assert set(areas) == {"saude", "educacao", "administracao"}

    def test_should_return_empty_when_unrelated(self) -> None:
        assert classify_areas("Edital de engenharia aeroespacial") == ()

    def test_should_ignore_accents_and_case(self) -> None:
        assert classify_areas("EDUCAÇÃO SUPERIOR") == ("educacao",)


class TestLooksLikeEdital:
    def test_should_accept_edital(self) -> None:
        assert looks_like_edital("Edital 01/2026 - bolsas de pesquisa")

    def test_should_accept_call_for_proposals(self) -> None:
        assert looks_like_edital("Call for proposals: health innovation")

    def test_should_reject_plain_navigation(self) -> None:
        assert looks_like_edital("Página inicial") is False

    def test_should_handle_none(self) -> None:
        assert looks_like_edital(None) is False


class TestDetectScope:
    def test_should_detect_international(self) -> None:
        assert detect_scope("Horizon Europe international call") == "internacional"

    def test_should_default_to_national(self) -> None:
        assert detect_scope("Edital regional") == "nacional"

    def test_should_respect_default(self) -> None:
        assert detect_scope("Edital genérico", default="internacional") == "internacional"


class TestDetectStatus:
    def test_should_detect_open(self) -> None:
        assert detect_status("Inscrições abertas até 30/09") == "aberto"

    def test_should_detect_upcoming(self) -> None:
        assert detect_status("Edital previsto para o segundo semestre") == "previsto"

    def test_should_detect_closed(self) -> None:
        assert detect_status("Chamada encerrada - resultado divulgado") == "encerrado"

    def test_should_prioritize_closed_over_open(self) -> None:
        assert detect_status("Inscrições encerradas") == "encerrado"

    def test_should_return_unknown_without_markers(self) -> None:
        assert detect_status("Edital 01/2026") == "desconhecido"


class TestParseDate:
    def test_should_parse_brazilian(self) -> None:
        assert parse_date("09/08/2026") == date(2026, 8, 9)

    def test_should_parse_iso(self) -> None:
        assert parse_date("2026-08-09") == date(2026, 8, 9)

    def test_should_parse_iso_with_time_and_tz(self) -> None:
        assert parse_date("2026-08-09T10:00:00Z") == date(2026, 8, 9)

    def test_should_parse_rfc822_pubdate(self) -> None:
        assert parse_date("Sat, 09 Aug 2026 10:00:00 +0000") == date(2026, 8, 9)

    def test_should_parse_extended_portuguese(self) -> None:
        assert parse_date("9 de agosto de 2026") == date(2026, 8, 9)

    def test_should_return_none_on_garbage(self) -> None:
        assert parse_date("qualquer coisa") is None

    def test_should_return_none_on_empty(self) -> None:
        assert parse_date(None) is None
