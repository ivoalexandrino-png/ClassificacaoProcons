"""Testes do cliente Gemini."""

from classificacao_procons.gemini.client import (
    DEFAULT_GEMINI_MODEL,
    apply_multa_replacement,
    enforce_portal_character_limit,
    get_model_from_env,
)


class TestGeminiHelpers:
    def test_should_use_gemini_2_5_flash_as_default_model(self) -> None:
        assert DEFAULT_GEMINI_MODEL == "gemini-2.5-flash"
        assert get_model_from_env() == "gemini-2.5-flash"

    def test_should_replace_multa_de_40_percent(self) -> None:
        text = "A empresa aplicará multa de 40% conforme contrato."
        assert "multa proporcional ao tempo restante" in apply_multa_replacement(text)
        assert "40%" not in apply_multa_replacement(text)

    def test_should_enforce_portal_character_limit(self) -> None:
        text = "a" * 1100
        result = enforce_portal_character_limit(text, max_chars=1024)
        assert len(result) <= 1024
