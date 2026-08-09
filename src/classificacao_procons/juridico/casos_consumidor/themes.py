"""Classificação temática da reclamação (regras + Gemini)."""

from __future__ import annotations

import json
import re
import unicodedata

from classificacao_procons.gemini.client import (
    GeminiClientError,
    _gemini_request,
    get_api_key_from_env,
    get_model_from_env,
    list_generate_content_models,
    resolve_gemini_model,
)
from classificacao_procons.juridico.casos_consumidor.models import CaseTheme

_THEME_KEYWORDS: dict[CaseTheme, tuple[str, ...]] = {
    CaseTheme.RENOVACAO_AUTOMATICA: (
        "renovacao automatica",
        "renovação automática",
        "cobranca apos cancel",
        "cobrança após cancel",
        "renovou sozinha",
        "renovou sem autorizacao",
        "renovou sem autorização",
        "cobrou novamente",
        "assinatura renovada",
    ),
    CaseTheme.PROBLEMA_ENTREGA: (
        "nao recebi",
        "não recebi",
        "nao chegou",
        "não chegou",
        "entrega",
        "atraso na entrega",
        "extravi",
        "jadlog",
        "correios",
        "rastreio",
        "caixa nao",
        "box nao",
    ),
    CaseTheme.PROBLEMA_PAGAMENTO: (
        "cobranca indevida",
        "cobrança indevida",
        "cobrou duas vezes",
        "duplicidade",
        "cartao",
        "cartão",
        "boleto",
        "estorno nao",
        "estorno não",
        "chargeback",
        "pagamento indevido",
    ),
    CaseTheme.PROBLEMA_CANCELAMENTO: (
        "cancelamento",
        "cancelar assinatura",
        "pedi cancelamento",
        "nao consegui cancelar",
        "não consegui cancelar",
        "continua cobrando apos cancel",
        "continua cobrando após cancel",
        "rescindir",
    ),
    CaseTheme.PROBLEMA_EXPERIENCIA: (
        "produto veio errado",
        "itens errados",
        "qualidade",
        "alergia",
        "reacao",
        "reação",
        "app",
        "site",
        "atendimento",
        "sac",
        "experiencia ruim",
        "experiência ruim",
    ),
}

_VALID_THEMES = frozenset(CaseTheme)


class ThemeClassificationError(RuntimeError):
    """Erro ao classificar tema do caso."""


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


def classify_theme_from_text(text: str) -> tuple[CaseTheme, tuple[CaseTheme, ...], str]:
    """Retorna tema principal, secundários e confiança (high/medium/low)."""
    normalized = _normalize(text)
    if not normalized:
        return CaseTheme.OUTROS, (), "low"

    scores: dict[CaseTheme, int] = {theme: 0 for theme in CaseTheme if theme != CaseTheme.OUTROS}
    for theme, keywords in _THEME_KEYWORDS.items():
        for keyword in keywords:
            if _normalize(keyword) in normalized:
                scores[theme] += 1

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_theme, best_score = ranked[0]
    if best_score == 0:
        return CaseTheme.OUTROS, (), "low"

    secondary = tuple(
        theme for theme, score in ranked[1:] if score > 0 and score >= best_score - 1
    )
    confidence = "high" if best_score >= 2 else "medium"
    return best_theme, secondary, confidence


def _extract_json_block(text: str) -> dict[str, object]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    raw = fenced.group(1) if fenced else text.strip()
    if not raw.startswith("{"):
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ThemeClassificationError("Gemini retornou JSON inválido.")
    return payload


def _parse_theme(value: object) -> CaseTheme:
    if not isinstance(value, str):
        return CaseTheme.OUTROS
    key = value.strip().casefold().replace(" ", "_").replace("-", "_")
    mapping = {
        "renovacao_automatica": CaseTheme.RENOVACAO_AUTOMATICA,
        "problema_entrega": CaseTheme.PROBLEMA_ENTREGA,
        "problema_pagamento": CaseTheme.PROBLEMA_PAGAMENTO,
        "problema_cancelamento": CaseTheme.PROBLEMA_CANCELAMENTO,
        "problema_experiencia": CaseTheme.PROBLEMA_EXPERIENCIA,
        "outros": CaseTheme.OUTROS,
    }
    return mapping.get(key, CaseTheme.OUTROS)


def classify_theme_with_gemini(
    *,
    text: str,
    consumer_folder: str,
    api_key: str | None = None,
    model: str | None = None,
) -> tuple[CaseTheme, tuple[CaseTheme, ...], str, str | None]:
    key = api_key or get_api_key_from_env()
    if not key:
        raise ThemeClassificationError("GEMINI_API_KEY não configurada.")

    selected_model = model
    if not selected_model:
        available_models = list_generate_content_models(api_key=key)
        selected_model = resolve_gemini_model(
            available_models=available_models,
            preferred=get_model_from_env(),
        )

    prompt = (
        "Classifique a reclamação de consumidor (assinatura glam/B4A) em JSON válido:\n"
        "{\n"
        '  "primary_theme": '
        '"renovacao_automatica|problema_entrega|problema_pagamento|'
        'problema_cancelamento|problema_experiencia|outros",\n'
        '  "secondary_themes": ["..."],\n'
        '  "confidence": "high|medium|low",\n'
        '  "evidence": "frase curta do texto que justifica"\n'
        "}\n"
        "Use apenas uma primary_theme. secondary_themes pode ser lista vazia.\n"
        f"Pasta/consumidor: {consumer_folder}\n"
        f"Texto:\n{text[:12000]}\n"
    )
    try:
        response = _gemini_request(
            api_key=key,
            model=selected_model,
            parts=[{"text": prompt}],
        )
    except GeminiClientError as exc:
        raise ThemeClassificationError(str(exc)) from exc

    payload = _extract_json_block(response)
    primary = _parse_theme(payload.get("primary_theme"))
    secondary_raw = payload.get("secondary_themes")
    secondary: list[CaseTheme] = []
    if isinstance(secondary_raw, list):
        for item in secondary_raw:
            theme = _parse_theme(item)
            if theme != primary and theme not in secondary:
                secondary.append(theme)
    confidence = str(payload.get("confidence", "medium")).strip().casefold()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    evidence = str(payload["evidence"]).strip() if payload.get("evidence") else None
    return primary, tuple(secondary), confidence, evidence
