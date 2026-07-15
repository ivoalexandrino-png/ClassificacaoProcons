"""Cliente Gemini para elaboração de respostas."""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"
ENV_GEMINI_API_KEY = "GEMINI_API_KEY"
ENV_GEMINI_MODEL = "GEMINI_MODEL"
MAX_GEMINI_RETRIES = 3
MAX_PORTAL_CHARACTERS = 1024
MULTA_40_PATTERN = re.compile(r"multa de 40\s*%", re.IGNORECASE)
MULTA_REPLACEMENT = "multa proporcional ao tempo restante"


class GeminiClientError(RuntimeError):
    """Erro ao gerar conteúdo com Gemini."""


@dataclass(frozen=True)
class GeneratedResponse:
    analysis: str
    draft: str
    final_response: str
    portal_summary: str


def get_api_key_from_env() -> str | None:
    api_key = os.environ.get(ENV_GEMINI_API_KEY, "").strip()
    return api_key or None


def get_model_from_env() -> str:
    model = os.environ.get(ENV_GEMINI_MODEL, DEFAULT_GEMINI_MODEL).strip()
    return model or DEFAULT_GEMINI_MODEL


def apply_multa_replacement(text: str) -> str:
    return MULTA_40_PATTERN.sub(MULTA_REPLACEMENT, text)


def enforce_portal_character_limit(text: str, *, max_chars: int = MAX_PORTAL_CHARACTERS) -> str:
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned
    truncated = cleaned[:max_chars].rstrip()
    last_space = truncated.rfind(" ")
    if last_space > max_chars - 120:
        return truncated[:last_space].rstrip()
    return truncated


def _gemini_request(
    *,
    api_key: str,
    model: str,
    parts: list[dict[str, object]],
) -> str:
    url = f"{GEMINI_API_BASE}/models/{model}:generateContent?key={api_key}"
    payload = {"contents": [{"parts": parts}]}
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    last_error: GeminiClientError | None = None
    for attempt in range(MAX_GEMINI_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt < MAX_GEMINI_RETRIES - 1:
                time.sleep(8 * (attempt + 1))
                continue
            if exc.code == 429:
                raise GeminiClientError(
                    "Limite gratuito do Gemini esgotado. Aguarde alguns minutos e tente "
                    "de novo, ou ative cobrança em https://aistudio.google.com/apikey",
                ) from exc
            raise GeminiClientError(f"Gemini HTTP {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise GeminiClientError(f"Gemini indisponível: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise GeminiClientError("Gemini retornou resposta inválida.") from exc
        else:
            candidates = body.get("candidates", [])
            if not candidates:
                raise GeminiClientError("Gemini não retornou candidatos de resposta.")

            content = candidates[0].get("content", {})
            response_parts = content.get("parts", [])
            texts = [str(part.get("text", "")) for part in response_parts if part.get("text")]
            if not texts:
                raise GeminiClientError("Gemini retornou resposta vazia.")
            return "\n".join(texts).strip()

    if last_error is not None:
        raise last_error
    raise GeminiClientError("Gemini indisponível após várias tentativas.")


def _pdf_part(pdf_path: Path) -> dict[str, object]:
    encoded = base64.b64encode(pdf_path.read_bytes()).decode("ascii")
    return {"inline_data": {"mime_type": "application/pdf", "data": encoded}}


def generate_procon_response(
    *,
    complaint_pdf_path: Path,
    sac_summary: str,
    supporting_file_names: list[str],
    consumer_name: str,
    protocol_number: str,
    api_key: str | None = None,
    model: str | None = None,
) -> GeneratedResponse:
    """Executa a cadeia de prompts para elaborar a resposta ao Procon."""
    key = api_key or get_api_key_from_env()
    if not key:
        raise GeminiClientError("GEMINI_API_KEY não configurada.")

    selected_model = model or get_model_from_env()

    if not complaint_pdf_path.exists():
        raise GeminiClientError(f"PDF da reclamação não encontrado: {complaint_pdf_path}")

    supporting_list = "\n".join(f"- {name}" for name in supporting_file_names) or "- (nenhum)"

    analysis_prompt = (
        "Você é advogado(a) de defesa do consumidor em resposta ao Procon-SP.\n"
        f"Consumidor: {consumer_name}\n"
        f"Protocolo: {protocol_number}\n\n"
        "Analise o PDF da reclamação anexo e produza:\n"
        "1) resumo objetivo dos fatos alegados;\n"
        "2) pontos jurídicos relevantes;\n"
        "3) riscos e oportunidades de defesa.\n"
        "Responda em português do Brasil."
    )
    analysis = _gemini_request(
        api_key=key,
        model=selected_model,
        parts=[{"text": analysis_prompt}, _pdf_part(complaint_pdf_path)],
    )

    draft_prompt = (
        "Com base na análise abaixo e no relato do SAC, redija uma resposta inicial ao Procon.\n\n"
        f"ANÁLISE:\n{analysis}\n\n"
        f"RELATO DO SAC:\n{sac_summary}\n\n"
        f"DOCUMENTOS ANEXADOS PELO SAC:\n{supporting_list}\n\n"
        "A resposta deve ser formal, clara e fundamentada nos documentos."
    )
    draft = _gemini_request(api_key=key, model=selected_model, parts=[{"text": draft_prompt}])

    rewrite_prompt = (
        "Reescreva a resposta abaixo tornando-a mais detalhada, persuasiva e bem fundamentada, "
        "sem inventar fatos que não estejam na análise ou no relato do SAC.\n\n"
        f"RESPOSTA ATUAL:\n{draft}"
    )
    final_response = _gemini_request(
        api_key=key,
        model=selected_model,
        parts=[{"text": rewrite_prompt}],
    )
    final_response = apply_multa_replacement(final_response)

    summary_prompt = (
        "Resuma a resposta abaixo para o campo de resposta do portal do Procon-SP, "
        f"com no máximo {MAX_PORTAL_CHARACTERS} caracteres, mantendo os argumentos centrais.\n"
        "Não use markdown. Retorne apenas o texto final.\n\n"
        f"RESPOSTA COMPLETA:\n{final_response}"
    )
    portal_summary = _gemini_request(
        api_key=key,
        model=selected_model,
        parts=[{"text": summary_prompt}],
    )
    portal_summary = apply_multa_replacement(portal_summary)
    portal_summary = enforce_portal_character_limit(portal_summary)

    return GeneratedResponse(
        analysis=analysis,
        draft=draft,
        final_response=final_response,
        portal_summary=portal_summary,
    )
