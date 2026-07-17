"""Consulta de andamento processual na API pública do DataJud (CNJ)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime

from classificacao_procons.juridico.cnj import datajud_alias, process_number_digits
from classificacao_procons.juridico.models import CaseMovement

DATAJUD_BASE_URL = "https://api-publica.datajud.cnj.jus.br"
ENV_DATAJUD_API_KEY = "DATAJUD_API_KEY"
REQUEST_TIMEOUT_SECONDS = 30


class DataJudError(RuntimeError):
    """Erro ao consultar a API pública do DataJud."""


def get_api_key_from_env() -> str | None:
    api_key = os.environ.get(ENV_DATAJUD_API_KEY, "").strip()
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


def fetch_case_movements(
    process_number: str,
    *,
    api_key: str | None = None,
    alias: str | None = None,
    limit: int = 20,
) -> list[CaseMovement]:
    """Busca os andamentos mais recentes de um processo pelo número CNJ."""
    key = api_key or get_api_key_from_env()
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
    request = urllib.request.Request(
        f"{DATAJUD_BASE_URL}/api_publica_{resolved_alias}/_search",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"APIKey {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise DataJudError(f"DataJud HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise DataJudError(f"DataJud indisponível: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise DataJudError("DataJud retornou resposta inválida.") from exc

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
