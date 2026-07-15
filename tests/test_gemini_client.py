"""Testes do cliente Gemini."""

from classificacao_procons.gemini.client import (
    apply_multa_replacement,
    enforce_portal_character_limit,
)


class TestGeminiHelpers:
    def test_should_replace_multa_de_40_percent(self) -> None:
        text = "A empresa aplicará multa de 40% conforme contrato."
        assert "multa proporcional ao tempo restante" in apply_multa_replacement(text)
        assert "40%" not in apply_multa_replacement(text)

    def test_should_enforce_portal_character_limit(self) -> None:
        text = "a" * 1100
        result = enforce_portal_character_limit(text, max_chars=1024)
        assert len(result) <= 1024
