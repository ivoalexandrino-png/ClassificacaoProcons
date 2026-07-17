"""Testes da numeração única CNJ (extração, tribunal e alias DataJud)."""

from classificacao_procons.juridico.cnj import (
    datajud_alias,
    extract_process_number,
    process_number_digits,
    tribunal_acronym,
)


class TestExtractProcessNumber:
    def test_should_extract_formatted_number_when_present(self) -> None:
        text = "Processo nº 1001234-56.2026.8.26.0100 em trâmite."
        assert extract_process_number(text) == "1001234-56.2026.8.26.0100"

    def test_should_normalize_number_when_unformatted(self) -> None:
        assert extract_process_number("autos 10012345620268260100") == (
            "1001234-56.2026.8.26.0100"
        )

    def test_should_return_none_when_no_number(self) -> None:
        assert extract_process_number("sem processo aqui") is None

    def test_should_return_none_when_text_is_empty(self) -> None:
        assert extract_process_number("") is None


class TestProcessNumberDigits:
    def test_should_strip_formatting_when_number_is_formatted(self) -> None:
        assert process_number_digits("1001234-56.2026.8.26.0100") == "10012345620268260100"


class TestTribunalAcronym:
    def test_should_map_justica_estadual_sp(self) -> None:
        assert tribunal_acronym("1001234-56.2026.8.26.0100") == "TJSP"

    def test_should_map_distrito_federal_to_tjdft(self) -> None:
        assert tribunal_acronym("1001234-56.2026.8.07.0001") == "TJDFT"

    def test_should_map_justica_federal(self) -> None:
        assert tribunal_acronym("0001234-56.2026.4.03.6100") == "TRF3"

    def test_should_map_justica_do_trabalho(self) -> None:
        assert tribunal_acronym("0001234-56.2026.5.02.0011") == "TRT2"

    def test_should_map_tst_when_tribunal_code_is_zero(self) -> None:
        assert tribunal_acronym("0001234-56.2026.5.00.0000") == "TST"

    def test_should_return_none_when_number_is_invalid(self) -> None:
        assert tribunal_acronym("não é um processo") is None

    def test_should_return_none_when_estadual_tr_is_unknown(self) -> None:
        assert tribunal_acronym("1001234-56.2026.8.99.0100") is None


class TestDatajudAlias:
    def test_should_lowercase_acronym_for_alias(self) -> None:
        assert datajud_alias("1001234-56.2026.8.26.0100") == "tjsp"

    def test_should_return_none_for_stf(self) -> None:
        assert datajud_alias("1001234-56.2026.1.00.0000") is None

    def test_should_return_none_when_number_is_invalid(self) -> None:
        assert datajud_alias("123") is None
