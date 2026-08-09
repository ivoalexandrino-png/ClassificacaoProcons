"""Testes de normalização do Questor (situação, datas, CNPJ)."""

from datetime import date

import pytest

from classificacao_procons.questor.parser import (
    leitura_is_lida,
    normalize_cnpj,
    normalize_situacao,
    parse_brazilian_date,
    situacao_from_questor_code,
)


class TestNormalizeSituacao:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Negativa", "negativa"),
            ("CERTIDÃO NEGATIVA", "negativa"),
            ("Regular", "negativa"),
            ("Positiva", "positiva"),
            ("Certidão Positiva com débitos", "positiva"),
            ("Positiva com efeitos de negativa", "positiva_com_efeitos_negativa"),
            ("CPEN", "positiva_com_efeitos_negativa"),
            ("Vencida", "vencida"),
            ("Validade vencida", "vencida"),
            ("Indisponível", "indisponivel"),
            ("Não emitida", "indisponivel"),
            ("Erro ao emitir", "indisponivel"),
            ("Irregular", "positiva"),
            ("Regular", "negativa"),
            ("Neutro", "neutra"),
            ("Restrição", "restricao"),
            ("Falha", "indisponivel"),
        ],
    )
    def test_should_map_known_labels(self, raw: str, expected: str) -> None:
        assert normalize_situacao(raw) == expected


class TestQuestorEnums:
    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            (0, "positiva"),
            (1, "negativa"),
            (2, "neutra"),
            (3, "indisponivel"),
            (5, "restricao"),
            (99, "desconhecida"),
            (None, "desconhecida"),
        ],
    )
    def test_situacao_from_questor_code(self, code: int | None, expected: str) -> None:
        assert situacao_from_questor_code(code) == expected

    @pytest.mark.parametrize(("code", "lida"), [(0, False), (1, False), (2, True), (None, False)])
    def test_leitura_is_lida(self, code: int | None, lida: bool) -> None:
        assert leitura_is_lida(code) is lida

    def test_should_prefer_efeitos_negativa_over_positiva(self) -> None:
        assert normalize_situacao("Positiva com efeito de negativa") == (
            "positiva_com_efeitos_negativa"
        )

    @pytest.mark.parametrize("raw", ["", None, "   ", "xyz qualquer"])
    def test_should_return_desconhecida_for_unknown(self, raw: str | None) -> None:
        assert normalize_situacao(raw) == "desconhecida"


class TestParseBrazilianDate:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("10/07/2026", date(2026, 7, 10)),
            ("10-07-2026", date(2026, 7, 10)),
            ("2026-07-10", date(2026, 7, 10)),
            ("  10/07/2026 ", date(2026, 7, 10)),
        ],
    )
    def test_should_parse_supported_formats(self, raw: str, expected: date) -> None:
        assert parse_brazilian_date(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "não é data", "31/31/2026"])
    def test_should_return_none_for_invalid(self, raw: str | None) -> None:
        assert parse_brazilian_date(raw) is None


class TestNormalizeCnpj:
    def test_should_keep_only_digits(self) -> None:
        assert normalize_cnpj("12.345.678/0001-99") == "12345678000199"

    @pytest.mark.parametrize("raw", [None, "", "sem digitos"])
    def test_should_return_none_when_no_digits(self, raw: str | None) -> None:
        assert normalize_cnpj(raw) is None
