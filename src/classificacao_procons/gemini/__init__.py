"""Cliente Gemini para elaboração de respostas."""

from classificacao_procons.gemini.client import (
    GeminiClientError,
    GeminiQuotaError,
    GeneratedResponse,
    apply_multa_replacement,
    enforce_portal_character_limit,
    generate_procon_response,
    get_api_key_from_env,
)

__all__ = [
    "GeminiClientError",
    "GeminiQuotaError",
    "GeneratedResponse",
    "apply_multa_replacement",
    "enforce_portal_character_limit",
    "generate_procon_response",
    "get_api_key_from_env",
]
