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
from datetime import date
from pathlib import Path

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
MODEL_PREFERENCE_ORDER = (
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
)
ENV_GEMINI_API_KEY = "GEMINI_API_KEY"
ENV_GEMINI_MODEL = "GEMINI_MODEL"
MAX_GEMINI_RETRIES = 8
RETRYABLE_GEMINI_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
MAX_PORTAL_CHARACTERS = 1024
MULTA_40_PATTERN = re.compile(r"multa de 40\s*%", re.IGNORECASE)
MULTA_REPLACEMENT = "multa proporcional ao tempo restante"
_META_PREAMBLE_PATTERN = re.compile(
    r"^.*?(?:aqui está|segue (?:abaixo|a)|versão reestruturada|conforme solicitado).*?\n---\s*\n+",
    re.IGNORECASE | re.DOTALL,
)
_FORMAL_RESPONSE_START = re.compile(
    r"(?im)^(?:#{1,3}\s*)?\**(?:ilustríssim|prezado|ao\s+procon|excelentíssim)",
)
_DATE_PLACEHOLDER_PATTERN = re.compile(
    r"\[(?:data\s*atual|data|DATA\s*ATUAL)\]",
    re.IGNORECASE,
)
_HEADER_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
_HORIZONTAL_RULE_PATTERN = re.compile(r"^[-*_]{3,}\s*$")


class GeminiClientError(RuntimeError):
    """Erro ao gerar conteúdo com Gemini."""


class GeminiQuotaError(GeminiClientError):
    """Cota do Gemini esgotada (HTTP 429). Condição transitória — tentar depois."""


# Circuit breaker de cota (legado): cooldown global desativado — bloqueava
# casos longos (ex.: vários PDFs digitalizados na pasta Informações).
QUOTA_COOLDOWN_SECONDS = 600
_quota_cooldown_until = 0.0


def _quota_cooldown_active() -> bool:
    return False


def _start_quota_cooldown() -> None:
    return


def reset_quota_cooldown() -> None:
    """Zera o cooldown (para testes ou retomada manual)."""
    global _quota_cooldown_until
    _quota_cooldown_until = 0.0


@dataclass(frozen=True)
class GeneratedResponse:
    analysis: str
    draft: str
    final_response: str
    portal_summary: str


def get_api_key_from_env() -> str | None:
    api_key = os.environ.get(ENV_GEMINI_API_KEY, "").strip()
    return api_key or None


def get_model_from_env() -> str | None:
    model = os.environ.get(ENV_GEMINI_MODEL, "").strip()
    return model or None


def normalize_model_name(model: str) -> str:
    return model.removeprefix("models/").strip()


def list_generate_content_models(*, api_key: str) -> list[str]:
    """Lista modelos disponíveis para generateContent nesta API key."""
    url = f"{GEMINI_API_BASE}/models?key={api_key}"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise GeminiClientError(f"Gemini HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise GeminiClientError(f"Gemini indisponível: {exc.reason}") from exc
    except OSError as exc:
        raise GeminiClientError(f"Gemini indisponível: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GeminiClientError("Gemini retornou lista de modelos inválida.") from exc

    models: list[str] = []
    for entry in body.get("models", []):
        methods = entry.get("supportedGenerationMethods", [])
        if "generateContent" not in methods:
            continue
        name = normalize_model_name(str(entry.get("name", "")))
        if name:
            models.append(name)
    return models


def resolve_gemini_model(
    *,
    available_models: list[str],
    preferred: str | None = None,
) -> str:
    """Escolhe o melhor modelo compatível com a API key."""
    if not available_models:
        raise GeminiClientError("Nenhum modelo Gemini disponível para esta API key.")

    available_set = set(available_models)
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    candidates.append(DEFAULT_GEMINI_MODEL)
    candidates.extend(MODEL_PREFERENCE_ORDER)

    seen: set[str] = set()
    for model in candidates:
        normalized = normalize_model_name(model)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if normalized in available_set:
            return normalized

    for name in available_models:
        if "flash" in name or "pro" in name:
            return name

    raise GeminiClientError(
        "Nenhum modelo Gemini compatível encontrado. "
        f"Disponíveis: {', '.join(available_models[:8])}",
    )


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


def strip_gemini_meta_preamble(text: str) -> str:
    cleaned = text.strip()
    without_rule = _META_PREAMBLE_PATTERN.sub("", cleaned)
    if without_rule != cleaned:
        cleaned = without_rule

    formal_match = _FORMAL_RESPONSE_START.search(cleaned)
    if formal_match and formal_match.start() > 0:
        prefix = cleaned[: formal_match.start()].strip()
        if re.search(
            r"(?i)(aqui está|versão reestruturada|argumentação jurídica|"
            r"segue abaixo|conforme solicitado)",
            prefix,
        ):
            cleaned = cleaned[formal_match.start() :].strip()

    return cleaned.lstrip("-").strip()


def _strip_inline_markdown(text: str) -> str:
    current = text.strip()
    for _ in range(4):
        updated = re.sub(r"\*\*(.+?)\*\*", r"\1", current)
        updated = re.sub(r"\*(.+?)\*", r"\1", updated)
        updated = re.sub(r"__(.+?)__", r"\1", updated)
        updated = re.sub(r"_(.+?)_", r"\1", updated)
        if updated == current:
            break
        current = updated
    return current


def _collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text.strip())


def strip_markdown_formatting(text: str) -> str:
    """Converte markdown comum do Gemini em texto corrido para documento jurídico."""
    lines: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            lines.append("")
            continue
        if _HORIZONTAL_RULE_PATTERN.match(stripped):
            lines.append("")
            continue
        if stripped.startswith(">"):
            stripped = stripped.lstrip(">").strip()

        header_match = _HEADER_PATTERN.match(stripped)
        if header_match:
            title = _strip_inline_markdown(header_match.group(2).strip())
            if title:
                lines.append(title.upper())
                lines.append("")
            continue

        lines.append(_strip_inline_markdown(stripped))

    return _collapse_blank_lines("\n".join(lines))


def replace_response_date_placeholders(
    text: str,
    *,
    signed_date: date | None = None,
) -> str:
    """Substitui placeholders de data por data real (padrão: hoje)."""
    reference = signed_date or date.today()
    formatted = reference.strftime("%d/%m/%Y")
    updated = _DATE_PLACEHOLDER_PATTERN.sub(formatted, text)
    updated = re.sub(
        r"(São Paulo,)\s*\[Data Atual\]\.?",
        rf"\1 {formatted}.",
        updated,
        flags=re.IGNORECASE,
    )
    updated = re.sub(
        r"(São Paulo,)\s*\.(?=\s*\n)",
        rf"\1 {formatted}.",
        updated,
        flags=re.IGNORECASE,
    )
    return updated


def finalize_procon_response_text(
    text: str,
    *,
    signed_date: date | None = None,
) -> str:
    """Aplica pós-processamento padrão ao texto da resposta ao Procon."""
    normalized = strip_gemini_meta_preamble(text)
    normalized = replace_response_date_placeholders(normalized, signed_date=signed_date)
    normalized = strip_markdown_formatting(normalized)
    return apply_multa_replacement(normalized)


def _is_retryable_gemini_http_error(code: int) -> bool:
    return code in RETRYABLE_GEMINI_HTTP_CODES


def _gemini_retry_delay_seconds(*, code: int, attempt: int) -> int:
    if code == 429:
        return 8 * (attempt + 1)
    return 4 * (2**attempt)


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
            if _is_retryable_gemini_http_error(exc.code) and attempt < MAX_GEMINI_RETRIES - 1:
                time.sleep(_gemini_retry_delay_seconds(code=exc.code, attempt=attempt))
                continue
            if exc.code == 429:
                raise GeminiQuotaError(
                    "Cota ou limite de requisições do Gemini atingido (HTTP 429). "
                    "Verifique billing em https://aistudio.google.com/apikey "
                    "ou configure OPENAI_API_KEY para fallback automático.",
                ) from exc
            if exc.code == 404:
                raise GeminiClientError(
                    f"Modelo Gemini '{model}' não encontrado ou descontinuado. "
                    "Defina GEMINI_MODEL com um modelo válido (ex.: gemini-3.5-flash) "
                    "em https://ai.google.dev/gemini-api/docs/models",
                ) from exc
            last_error = GeminiClientError(f"Gemini HTTP {exc.code}: {error_body}")
            raise last_error from exc
        except urllib.error.URLError as exc:
            raise GeminiClientError(f"Gemini indisponível: {exc.reason}") from exc
        except OSError as exc:
            # Timeout no meio da leitura chega como TimeoutError (OSError),
            # sem virar URLError — tratar como indisponibilidade retentável.
            if attempt < MAX_GEMINI_RETRIES - 1:
                time.sleep(_gemini_retry_delay_seconds(code=503, attempt=attempt))
                continue
            raise GeminiClientError(f"Gemini indisponível: {exc}") from exc
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


def _ordered_model_candidates(
    *,
    available_models: list[str],
    preferred: str | None,
) -> list[str]:
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    candidates.append(DEFAULT_GEMINI_MODEL)
    candidates.extend(MODEL_PREFERENCE_ORDER)

    available_set = set(available_models)
    ordered: list[str] = []
    seen: set[str] = set()
    for model in candidates:
        normalized = normalize_model_name(model)
        if not normalized or normalized in seen or normalized not in available_set:
            continue
        seen.add(normalized)
        ordered.append(normalized)

    for name in available_models:
        if ("flash" in name or "pro" in name) and name not in seen:
            ordered.append(name)
            seen.add(name)
    return ordered


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
    from classificacao_procons.llm.procon_response import (
        generate_procon_response as generate_with_llm_providers,
    )

    return generate_with_llm_providers(
        complaint_pdf_path=complaint_pdf_path,
        sac_summary=sac_summary,
        supporting_file_names=supporting_file_names,
        consumer_name=consumer_name,
        protocol_number=protocol_number,
        api_key=api_key,
        model=model,
    )
