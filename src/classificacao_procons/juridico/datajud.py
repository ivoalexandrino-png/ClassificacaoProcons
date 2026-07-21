"""Consulta de andamento processual na API pública do DataJud (CNJ)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

from classificacao_procons.juridico.cnj import datajud_alias, process_number_digits
from classificacao_procons.juridico.models import CaseMovement

DATAJUD_BASE_URL = "https://api-publica.datajud.cnj.jus.br"
ENV_DATAJUD_API_KEY = "DATAJUD_API_KEY"
REQUEST_TIMEOUT_SECONDS = 30
MAX_DATAJUD_RETRIES = 4
RETRY_BASE_DELAY_SECONDS = 8
_RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
# Intervalo mínimo entre chamadas ao DataJud, para não estourar o rate limit
# do CNJ quando um lote grande de intimações é processado em sequência.
MIN_INTERVAL_SECONDS = 1.5
_last_request_at = 0.0


class DataJudError(RuntimeError):
    """Erro ao consultar a API pública do DataJud."""


def _normalize_api_key(raw: str) -> str:
    """Remove um prefixo ``APIKey``/``ApiKey`` colado junto ao valor do secret.

    O header enviado é ``Authorization: APIKey {key}``; se o secret já vier com
    o prefixo (formato comum na documentação do DataJud), ele seria duplicado
    e a API responderia HTTP 401.
    """
    cleaned = raw.strip()
    if cleaned.lower().startswith("apikey"):
        cleaned = cleaned[len("apikey"):].lstrip(" :").strip()
    return cleaned


def get_api_key_from_env() -> str | None:
    api_key = _normalize_api_key(os.environ.get(ENV_DATAJUD_API_KEY, ""))
    return api_key or None


def _parse_movement_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _movement_from_payload(payload: dict) -> CaseMovement | None:
    name = str(payload.get("nome", "")).strip()
    if not name:
        return None
    code = payload.get("codigo")
    return CaseMovement(
        movement_name=name,
        movement_code=int(code) if isinstance(code, int | str) and str(code).isdigit() else None,
        movement_datetime=_parse_movement_datetime(payload.get("dataHora")),
    )


def _throttle() -> None:
    """Espaça as chamadas ao DataJud para respeitar o rate limit do CNJ."""
    global _last_request_at
    now = time.monotonic()
    wait = MIN_INTERVAL_SECONDS - (now - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _request_with_retries(*, url: str, payload: dict, api_key: str) -> dict:
    """POST no DataJud com retry para 429/5xx e timeouts (backoff exponencial)."""
    last_error: DataJudError | None = None

    for attempt in range(MAX_DATAJUD_RETRIES):
        _throttle()
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"APIKey {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            last_error = DataJudError(f"DataJud HTTP {exc.code}: {error_body}")
            if exc.code not in _RETRYABLE_HTTP_CODES or attempt == MAX_DATAJUD_RETRIES - 1:
                raise last_error from exc
        except urllib.error.URLError as exc:
            raise DataJudError(f"DataJud indisponível: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise DataJudError("DataJud retornou resposta inválida.") from exc
        except OSError as exc:
            # Timeout de leitura no meio da resposta chega como TimeoutError,
            # que o urllib não converte em URLError — retentável.
            last_error = DataJudError(f"DataJud indisponível: {exc}")
            if attempt == MAX_DATAJUD_RETRIES - 1:
                raise last_error from exc
        time.sleep(RETRY_BASE_DELAY_SECONDS * (2**attempt))

    raise last_error if last_error else DataJudError("DataJud indisponível.")


def fetch_case_movements(
    process_number: str,
    *,
    api_key: str | None = None,
    alias: str | None = None,
    limit: int = 20,
) -> list[CaseMovement]:
    """Busca os andamentos mais recentes de um processo pelo número CNJ."""
    key = _normalize_api_key(api_key) if api_key else get_api_key_from_env()
    if not key:
        raise DataJudError(
            "DATAJUD_API_KEY não configurada. "
            "Obtenha a chave pública em https://datajud-wiki.cnj.jus.br/api-publica/",
        )

    resolved_alias = alias or datajud_alias(process_number)
    if not resolved_alias:
        raise DataJudError(
            f"Tribunal não suportado para o processo {process_number}. "
            "Informe o alias do DataJud manualmente (ex.: tjsp).",
        )

    payload = {
        "query": {"match": {"numeroProcesso": process_number_digits(process_number)}},
        "size": 1,
    }
    body = _request_with_retries(
        url=f"{DATAJUD_BASE_URL}/api_publica_{resolved_alias}/_search",
        payload=payload,
        api_key=key,
    )

    hits = body.get("hits", {}).get("hits", [])
    if not hits:
        return []

    source = hits[0].get("_source", {})
    raw_movements = source.get("movimentos", [])
    if not isinstance(raw_movements, list):
        return []

    movements = [
        movement
        for payload_item in raw_movements
        if isinstance(payload_item, dict)
        and (movement := _movement_from_payload(payload_item)) is not None
    ]
    movements.sort(key=_movement_sort_key, reverse=True)
    return movements[:limit]


def _movement_sort_key(movement: CaseMovement) -> float:
    moment = movement.movement_datetime
    if moment is None:
        return float("-inf")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()
