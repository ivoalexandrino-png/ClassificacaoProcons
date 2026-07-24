"""Testes de fallback e orquestração LLM."""

from pathlib import Path
from unittest.mock import patch

import pytest

from classificacao_procons.gemini.client import GeminiClientError, GeneratedResponse
from classificacao_procons.llm.procon_response import generate_procon_response


@patch("classificacao_procons.llm.procon_response._generate_with_openai")
@patch("classificacao_procons.llm.procon_response._generate_with_gemini")
@patch("classificacao_procons.llm.procon_response.get_openai_api_key_from_env")
@patch("classificacao_procons.llm.procon_response.get_api_key_from_env")
def test_should_fallback_to_openai_when_gemini_quota_exhausted(
    gemini_env_mock,
    openai_env_mock,
    gemini_generate_mock,
    openai_generate_mock,
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "complaint.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    gemini_env_mock.return_value = "gemini-key"
    openai_env_mock.return_value = "openai-key"
    gemini_generate_mock.side_effect = GeminiClientError(
        "Cota ou limite de requisições do Gemini atingido (HTTP 429).",
    )
    openai_generate_mock.return_value = GeneratedResponse(
        analysis="Análise",
        draft="Rascunho",
        final_response="Resposta final",
        portal_summary="Resumo",
    )

    result = generate_procon_response(
        complaint_pdf_path=pdf_path,
        sac_summary="Relato SAC",
        supporting_file_names=[],
        consumer_name="MARIA",
        protocol_number="123/2026",
    )

    assert result.final_response == "Resposta final"
    gemini_generate_mock.assert_called_once()
    openai_generate_mock.assert_called_once()


@patch("classificacao_procons.llm.procon_response.get_openai_api_key_from_env", return_value=None)
@patch("classificacao_procons.llm.procon_response.get_api_key_from_env", return_value=None)
def test_should_raise_when_no_llm_provider_configured(
    _gemini_env_mock,
    _openai_env_mock,
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "complaint.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    with pytest.raises(GeminiClientError, match="Nenhum provedor de IA configurado"):
        generate_procon_response(
            complaint_pdf_path=pdf_path,
            sac_summary="Relato SAC",
            supporting_file_names=[],
            consumer_name="MARIA",
            protocol_number="123/2026",
            api_key=None,
        )
