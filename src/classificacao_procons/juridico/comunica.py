"""Teor das comunicações processuais — API pública Comunica (PJe/CNJ).

É a mesma base do Domicílio Judicial Eletrônico: dado o número CNJ, retorna o
texto integral das intimações/citações expedidas, sem necessidade de login.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from classificacao_procons.juridico.cnj import process_number_digits
from classificacao_procons.juridico.models import CaseCommunication

COMUNICA_BASE_URL = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
REQUEST_TIMEOUT_SECONDS = 30


class ComunicaError(RuntimeError):
    """Erro ao consultar a API Comunica do PJe/CNJ."""


def _first_str(payload: dict, *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _communication_from_payload(payload: dict) -> CaseCommunication | None:
    text = _first_str(payload, "texto", "teor", "conteudo")
    if not text:
        return None
    return CaseCommunication(
        text=text,
        communication_type=_first_str(payload, "tipoComunicacao", "tipo_comunicacao", "tipo"),
        tribunal=_first_str(payload, "siglaTribunal", "sigla_tribunal"),
        organ=_first_str(payload, "nomeOrgao", "nome_orgao", "orgao"),
        available_date=_first_str(
            payload,
            "data_disponibilizacao",
            "dataDisponibilizacao",
            "datadisponibilizacao",
        ),
        link=_first_str(payload, "link"),
    )


def fetch_case_communications(
    process_number: str,
    *,
    limit: int = 5,
) -> list[CaseCommunication]:
    """Busca as comunicações mais recentes de um processo pelo número CNJ."""
    params = urllib.parse.urlencode(
        {
            "numeroProcesso": process_number_digits(process_number),
            "pagina": 1,
            "itensPorPagina": limit,
        },
    )
    request = urllib.request.Request(
        f"{COMUNICA_BASE_URL}?{params}",
        headers={"Accept": "application/json"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise ComunicaError(f"Comunica HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise ComunicaError(f"Comunica indisponível: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise ComunicaError("Comunica retornou resposta inválida.") from exc

    items = body.get("items", []) if isinstance(body, dict) else body
    if not isinstance(items, list):
        return []

    communications = [
        communication
        for payload_item in items
        if isinstance(payload_item, dict)
        and (communication := _communication_from_payload(payload_item)) is not None
    ]
    return communications[:limit]
