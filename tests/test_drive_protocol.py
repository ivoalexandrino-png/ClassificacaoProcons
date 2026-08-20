"""Testes de validação de protocolo no Drive."""

import pytest

from classificacao_procons.drive.client import DriveClientError
from classificacao_procons.drive.protocol import (
    build_disambiguated_folder_name,
    build_protocol_mismatch_error,
    extract_protocol_from_procon_pdf_name,
    is_protocol_mismatch_error,
    normalize_protocol_number,
    protocols_match,
    validate_complaint_pdf_protocol,
)


class TestProtocolHelpers:
    def test_should_normalize_protocol_with_slash_or_dash(self) -> None:
        assert normalize_protocol_number("1759897/2026") == "1759897-2026"
        assert normalize_protocol_number("1759897-2026") == "1759897-2026"

    def test_should_extract_protocol_from_standard_procon_pdf_name(self) -> None:
        name = (
            "Atendimento Procon - GABRIELE CELETE CUSTODIO JESUS - "
            "1759897-2026 - 15-08-2026.pdf"
        )
        assert extract_protocol_from_procon_pdf_name(name) == "1759897-2026"

    def test_should_match_protocols_with_slash_and_dash(self) -> None:
        assert protocols_match("1759897/2026", "1759897-2026")

    def test_should_build_disambiguated_folder_name(self) -> None:
        assert build_disambiguated_folder_name(
            consumer_name="GABRIELE CELETE CUSTODIO JESUS",
            protocol_number="1759897/2026",
        ) == "GABRIELE CELETE CUSTODIO JESUS - 1759897-2026"

    def test_should_raise_when_complaint_pdf_protocol_differs(self) -> None:
        pdf_name = (
            "Atendimento Procon - GABRIELE CELETE CUSTODIO JESUS - "
            "1656146-2026 - 15-07-2026.pdf"
        )
        with pytest.raises(DriveClientError, match="Pasta Docs SAC inconsistente"):
            validate_complaint_pdf_protocol(
                pdf_name=pdf_name,
                expected_protocol="1759897/2026",
            )

    def test_should_allow_matching_protocol(self) -> None:
        pdf_name = (
            "Atendimento Procon - GABRIELE CELETE CUSTODIO JESUS - "
            "1759897-2026 - 15-08-2026.pdf"
        )
        validate_complaint_pdf_protocol(
            pdf_name=pdf_name,
            expected_protocol="1759897/2026",
        )

    def test_should_flag_protocol_mismatch_error_prefix(self) -> None:
        message = build_protocol_mismatch_error(
            expected_protocol="1759897/2026",
            found_protocol="1656146/2026",
            pdf_name="Atendimento Procon - test.pdf",
        )
        assert is_protocol_mismatch_error(message)
