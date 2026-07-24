"""Cliente OpenAI (ChatGPT) para fallback na elaboração de respostas."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from classificacao_procons.gemini.client import GeminiClientError

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
ENV_OPENAI_API_KEY = "OPENAI_API_KEY"
ENV_OPENAI_MODEL = "OPENAI_MODEL"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
MAX_OPENAI_RETRIES = 5
RETRYABLE_OPENAI_HTTP_CODES = frozenset({429, 500, 502, 503, 504})


def get_api_key_from_env() -> str | None:
    api_key = os.environ.get(ENV_OPENAI_API_KEY, "").strip()
    return api_key or None


def get_model_from_env() -> str | None:
    model = os.environ.get(ENV_OPENAI_MODEL, "").strip()
    return model or None


def resolve_openai_model(*, preferred: str | None = None) -> str:
    if preferred:
        return preferred
    return get_model_from_env() or DEFAULT_OPENAI_MODEL


def _retry_delay_seconds(*, code: int, attempt: int) -> int:
    if code == 429:
        return 10 * (attempt + 1)
    return 4 * (2**attempt)


def chat_completion(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """Chama a API de chat da OpenAI e retorna o conteúdo da resposta."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.4,
    }
    request = urllib.request.Request(
        OPENAI_CHAT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    last_error: GeminiClientError | None = None
    for attempt in range(MAX_OPENAI_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            if exc.code in RETRYABLE_OPENAI_HTTP_CODES and attempt < MAX_OPENAI_RETRIES - 1:
                time.sleep(_retry_delay_seconds(code=exc.code, attempt=attempt))
                continue
            if exc.code == 429:
                raise GeminiClientError(
                    "Limite de requisições da OpenAI atingido (HTTP 429). "
                    "Verifique billing em https://platform.openai.com/account/billing",
                ) from exc
            raise GeminiClientError(f"OpenAI HTTP {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise GeminiClientError(f"OpenAI indisponível: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise GeminiClientError("OpenAI retornou resposta inválida.") from exc
        else:
            choices = body.get("choices", [])
            if not choices:
                raise GeminiClientError("OpenAI não retornou candidatos de resposta.")
            message = choices[0].get("message", {})
            content = str(message.get("content", "")).strip()
            if not content:
                raise GeminiClientError("OpenAI retornou resposta vazia.")
            return content

    if last_error is not None:
        raise last_error
    raise GeminiClientError("OpenAI indisponível após várias tentativas.")
