"""Chamadas de IA para classificar e redigir respostas."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from classificacao_procons.gemini.client import (
    GeminiClientError,
    _gemini_request,
    resolve_gemini_model,
)
from classificacao_procons.gemini.client import (
    get_api_key_from_env as get_gemini_key,
)
from classificacao_procons.llm.openai_client import (
    chat_completion as openai_chat,
)
from classificacao_procons.llm.openai_client import (
    get_api_key_from_env as get_openai_key,
)
from classificacao_procons.llm.openai_client import (
    resolve_openai_model,
)
from classificacao_procons.whatsapp.risk import RiskTier

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


class WhatsappLlmError(RuntimeError):
    """Falha ao gerar resposta com IA."""


@dataclass(frozen=True)
class LlmReplyResult:
    tier: RiskTier
    reply_text: str
    reasons: tuple[str, ...] = ()


def _parse_llm_json(raw: str) -> dict[str, object]:
    match = _JSON_BLOCK.search(raw.strip())
    if not match:
        raise WhatsappLlmError("IA não retornou JSON válido.")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise WhatsappLlmError("IA retornou JSON inválido.") from exc
    if not isinstance(data, dict):
        raise WhatsappLlmError("Formato inesperado da IA.")
    return data


def _normalize_tier(value: object) -> RiskTier:
    tier = str(value or "").strip().lower()
    if tier in {"routine", "ambiguous", "legal_high"}:
        return tier  # type: ignore[return-value]
    if tier in {"legal", "juridico", "jurídico", "high"}:
        return "legal_high"
    if tier in {"ambiguo", "ambíguo", "uncertain"}:
        return "ambiguous"
    return "ambiguous"


def _call_gemini(*, system_prompt: str, user_prompt: str, api_key: str, model: str) -> str:
    parts: list[dict[str, object]] = [
        {"text": f"{system_prompt}\n\n---\n\n{user_prompt}"},
    ]
    return _gemini_request(api_key=api_key, model=model, parts=parts)


def generate_whatsapp_reply(
    *,
    system_prompt: str,
    user_prompt: str,
    gemini_api_key: str | None = None,
    openai_api_key: str | None = None,
    gemini_model: str | None = None,
    openai_model: str | None = None,
) -> LlmReplyResult:
    """Gera tier + texto de resposta via Gemini (fallback OpenAI)."""
    gemini_key = gemini_api_key or get_gemini_key()
    openai_key = openai_api_key or get_openai_key()
    if not gemini_key and not openai_key:
        raise WhatsappLlmError(
            "Configure GEMINI_API_KEY e/ou OPENAI_API_KEY para respostas automáticas.",
        )

    raw: str | None = None
    last_error: Exception | None = None

    if gemini_key:
        try:
            model = resolve_gemini_model(api_key=gemini_key, preferred=gemini_model)
            raw = _call_gemini(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=gemini_key,
                model=model,
            )
        except GeminiClientError as exc:
            last_error = exc
            raw = None

    if raw is None and openai_key:
        try:
            raw = openai_chat(
                api_key=openai_key,
                model=resolve_openai_model(preferred=openai_model),
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except GeminiClientError as exc:
            last_error = exc
            raw = None

    if raw is None:
        raise WhatsappLlmError(str(last_error or "Nenhum provedor de IA respondeu."))

    data = _parse_llm_json(raw)
    tier = _normalize_tier(data.get("tier"))
    reply = str(data.get("reply", "")).strip()
    if not reply:
        raise WhatsappLlmError("IA retornou resposta vazia.")

    reasons_raw = data.get("reasons", [])
    reasons: tuple[str, ...] = ()
    if isinstance(reasons_raw, list):
        reasons = tuple(str(item) for item in reasons_raw if str(item).strip())

    return LlmReplyResult(tier=tier, reply_text=reply, reasons=reasons)
