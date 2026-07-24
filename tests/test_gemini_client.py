"""Testes do cliente Gemini."""

from datetime import date

import pytest

from classificacao_procons.gemini.client import (
    DEFAULT_GEMINI_MODEL,
    GeminiClientError,
    _gemini_retry_delay_seconds,
    _is_retryable_gemini_http_error,
    _ordered_model_candidates,
    apply_multa_replacement,
    enforce_portal_character_limit,
    finalize_procon_response_text,
    get_model_from_env,
    replace_response_date_placeholders,
    resolve_gemini_model,
    strip_gemini_meta_preamble,
)


class TestGeminiHelpers:
    def test_should_use_gemini_3_5_flash_as_default_model(self) -> None:
        assert DEFAULT_GEMINI_MODEL == "gemini-3.5-flash"
        assert get_model_from_env() is None

    def test_should_replace_multa_de_40_percent(self) -> None:
        text = "A empresa aplicará multa de 40% conforme contrato."
        assert "multa proporcional ao tempo restante" in apply_multa_replacement(text)
        assert "40%" not in apply_multa_replacement(text)

    def test_should_enforce_portal_character_limit(self) -> None:
        text = "a" * 1100
        result = enforce_portal_character_limit(text, max_chars=1024)
        assert len(result) <= 1024

    def test_should_strip_meta_preamble_before_formal_response(self) -> None:
        text = (
            "Aqui está uma versão reestruturada, com argumentação jurídica robusta.\n"
            "---\n\n"
            "**ILUSTRÍSSIMO(A) SENHOR(A) DIRETOR(A) DO PROCON-SP**\n"
            "Conteúdo da resposta."
        )
        cleaned = strip_gemini_meta_preamble(text)
        assert cleaned.startswith("**ILUSTRÍSSIMO")
        assert "Aqui está uma versão" not in cleaned

    def test_should_replace_date_placeholder(self) -> None:
        text = "São Paulo, [Data Atual].\n\nRepresentante Legal"
        updated = replace_response_date_placeholders(
            text,
            signed_date=date(2026, 7, 24),
        )
        assert "São Paulo, 24/07/2026." in updated
        assert "[Data Atual]" not in updated

    def test_should_finalize_response_text(self) -> None:
        text = (
            "Aqui está uma versão reestruturada.\n---\n\n"
            "**ILUSTRÍSSIMO(A) SENHOR(A)**\n"
            "São Paulo, [Data Atual]."
        )
        final = finalize_procon_response_text(text, signed_date=date(2026, 7, 24))
        assert final.startswith("**ILUSTRÍSSIMO")
        assert "24/07/2026" in final


class TestResolveGeminiModel:
    def test_should_resolve_preferred_model_when_available(self) -> None:
        available = ["gemini-3.5-flash", "gemini-2.5-flash"]
        assert (
            resolve_gemini_model(
                available_models=available,
                preferred="gemini-2.5-flash",
            )
            == "gemini-2.5-flash"
        )

    def test_should_pick_default_when_preferred_model_is_unavailable(self) -> None:
        available = ["gemini-3.5-flash", "gemini-flash-latest"]
        assert (
            resolve_gemini_model(
                available_models=available,
                preferred="gemini-2.5-flash",
            )
            == "gemini-3.5-flash"
        )

    def test_should_fallback_to_any_flash_model_when_preferences_missing(self) -> None:
        assert (
            resolve_gemini_model(
                available_models=["gemini-custom-flash-preview"],
            )
            == "gemini-custom-flash-preview"
        )

    def test_should_raise_when_no_compatible_model_exists(self) -> None:
        with pytest.raises(GeminiClientError, match="Nenhum modelo Gemini compatível"):
            resolve_gemini_model(
                available_models=["embedding-001"],
                preferred="gemini-3.5-flash",
            )

    def test_should_mark_503_as_retryable(self) -> None:
        assert _is_retryable_gemini_http_error(503) is True
        assert _is_retryable_gemini_http_error(400) is False

    def test_should_increase_retry_delay_for_503(self) -> None:
        assert _gemini_retry_delay_seconds(code=503, attempt=0) < _gemini_retry_delay_seconds(
            code=503,
            attempt=2,
        )

    def test_should_order_model_candidates_with_preferred_first(self) -> None:
        ordered = _ordered_model_candidates(
            available_models=["gemini-3.5-flash", "gemini-2.5-flash", "gemini-flash-latest"],
            preferred="gemini-2.5-flash",
        )
        assert ordered[0] == "gemini-2.5-flash"
        assert "gemini-3.5-flash" in ordered
