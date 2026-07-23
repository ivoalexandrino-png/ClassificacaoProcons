"""Testes do cliente Gemini."""

import io
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from classificacao_procons.gemini.client import (
    DEFAULT_GEMINI_MODEL,
    GeminiClientError,
    GeminiQuotaError,
    _gemini_request,
    _gemini_retry_delay_seconds,
    _is_retryable_gemini_http_error,
    _ordered_model_candidates,
    apply_multa_replacement,
    enforce_portal_character_limit,
    get_model_from_env,
    resolve_gemini_model,
)


class TestGeminiQuota:
    def test_should_raise_quota_error_on_429_after_retries(self) -> None:
        error_429 = urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b"quota"),
        )
        with (
            patch("urllib.request.urlopen", MagicMock(side_effect=error_429)),
            patch("classificacao_procons.gemini.client.time.sleep"),
            pytest.raises(GeminiQuotaError, match="Limite gratuito"),
        ):
            _gemini_request(api_key="k", model="gemini-3.5-flash", parts=[{"text": "oi"}])

    def test_quota_error_is_gemini_client_error(self) -> None:
        # subclasse: quem captura GeminiClientError também trata a cota (fallback)
        assert issubclass(GeminiQuotaError, GeminiClientError)


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
