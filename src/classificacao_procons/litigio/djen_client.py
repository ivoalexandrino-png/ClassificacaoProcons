"""Cliente da API pública do DJEN / Comunica PJe (comunicaapi.pje.jus.br).

O DJEN (Diário de Justiça Eletrônico Nacional, Resolução CNJ nº 455/2022)
centraliza intimações, citações e demais publicações de todos os tribunais
brasileiros. A API de consulta é pública (sem autenticação), mas só responde
para IPs de origem brasileira (geo-bloqueio); fora do Brasil ela retorna
HTTP 403.

Referência: https://www.cnj.jus.br/programas-e-acoes/processo-judicial-eletronico-pje/comunicacoes-processuais/
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from bs4 import BeautifulSoup

from classificacao_procons.litigio.models import AdvogadoDestinatario, Intimacao

DJEN_BASE_URL: Final = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
DJEN_ITEMS_PER_PAGE_MAX: Final = 50
DJEN_MAX_PAGINAS: Final = 200
DJEN_REQUEST_TIMEOUT_SECONDS: Final = 15
DJEN_RETRY_DELAY_SECONDS: Final = 1.0
DJEN_MAX_RETRIES_PAGINA: Final = 2

# Cada tribunal registra a inscrição da OAB com um sufixo diferente
# (originária, suplementar/transferência...). Sem consultar as variantes,
# a maior parte das publicações de uma OAB real fica invisível.
OAB_SUFIXOS: Final = ("", "-O", "-A", "-N", "-B", "-S", "-E")

_HTML_HOSTILE_ATTRS: Final = ("class", "style", "id")


class DjenClientError(RuntimeError):
    """Erro ao consultar a API do DJEN."""


@dataclass(frozen=True)
class DjenQueryOptions:
    data_inicio: date
    data_fim: date
    numero_oab: str | None = None
    uf_oab: str | None = None
    numero_processo: str | None = None
    sigla_tribunal: str | None = None


def _only_digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _sanitize_texto_html(html: str) -> str:
    """Remove vetores de HTML hostil (class/style/id, script, handlers on*)."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr in _HTML_HOSTILE_ATTRS or attr.startswith("on"):
                del tag[attr]
            elif attr in {"href", "src"} and str(tag[attr]).strip().lower().startswith(
                "javascript:",
            ):
                del tag[attr]
    return str(soup)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_advogados(raw_items: list[dict]) -> tuple[AdvogadoDestinatario, ...]:
    advogados: list[AdvogadoDestinatario] = []
    for item in raw_items or []:
        advogado = item.get("advogado") if isinstance(item, dict) else None
        if not isinstance(advogado, dict):
            continue
        numero_oab = str(advogado.get("numero_oab") or "").strip()
        if not numero_oab:
            continue
        advogados.append(
            AdvogadoDestinatario(
                nome=str(advogado.get("nome") or "").strip(),
                numero_oab=numero_oab,
                uf_oab=str(advogado.get("uf_oab") or "").strip(),
            ),
        )
    return tuple(advogados)


def parse_comunicacao_item(raw: dict) -> Intimacao | None:
    """Converte um item bruto da API em `Intimacao`.

    Retorna `None` quando faltam os campos mínimos (`id`/`numero_processo`),
    pois sem eles não há como deduplicar nem vincular a um processo.
    """
    item_id = raw.get("id")
    numero_processo = str(raw.get("numero_processo") or "").strip()
    if item_id is None or not numero_processo:
        return None

    data_disponibilizacao = _parse_date(raw.get("data_disponibilizacao"))
    if data_disponibilizacao is None:
        return None

    return Intimacao(
        id=int(item_id),
        hash=str(raw.get("hash") or ""),
        numero_processo=numero_processo,
        numero_processo_formatado=str(
            raw.get("numeroprocessocommascara") or numero_processo,
        ),
        tribunal=str(raw.get("siglaTribunal") or ""),
        tipo_comunicacao=str(raw.get("tipoComunicacao") or ""),
        tipo_documento=str(raw.get("tipoDocumento") or ""),
        orgao=str(raw.get("nomeOrgao") or ""),
        classe_processual=str(raw.get("nomeClasse") or ""),
        data_disponibilizacao=data_disponibilizacao,
        texto=_sanitize_texto_html(str(raw.get("texto") or "")),
        link=raw.get("link") or None,
        status=raw.get("status") or None,
        motivo_cancelamento=raw.get("motivo_cancelamento") or None,
        advogados=_parse_advogados(raw.get("destinatarioadvogados") or []),
    )


def _build_query_params(
    options: DjenQueryOptions,
    *,
    numero_oab_variante: str | None,
    pagina: int,
) -> dict[str, str]:
    params: dict[str, str] = {
        "dataDisponibilizacaoInicio": options.data_inicio.isoformat(),
        "dataDisponibilizacaoFim": options.data_fim.isoformat(),
        "pagina": str(pagina),
        "itensPorPagina": str(DJEN_ITEMS_PER_PAGE_MAX),
    }
    if numero_oab_variante:
        params["numeroOab"] = numero_oab_variante
    if options.uf_oab:
        params["ufOab"] = options.uf_oab
    if options.numero_processo:
        params["numeroProcesso"] = _only_digits(options.numero_processo)
    if options.sigla_tribunal:
        params["siglaTribunal"] = options.sigla_tribunal
    return params


def _http_get_json(params: dict[str, str]) -> dict:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{DJEN_BASE_URL}?{query}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=DJEN_REQUEST_TIMEOUT_SECONDS,
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise DjenClientError(
                "DJEN respondeu 403: a API do Comunica PJe só aceita requisições "
                "de IPs brasileiros. Execute a consulta a partir de uma região "
                "no Brasil (ex.: GCP southamerica-east1).",
            ) from exc
        raise DjenClientError(f"DJEN respondeu HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise DjenClientError(f"DJEN indisponível: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise DjenClientError("DJEN retornou resposta inválida.") from exc


def _fetch_pagina(
    options: DjenQueryOptions,
    *,
    numero_oab_variante: str | None,
    pagina: int,
) -> tuple[list[dict], int]:
    params = _build_query_params(
        options,
        numero_oab_variante=numero_oab_variante,
        pagina=pagina,
    )
    payload = _http_get_json(params)
    items = payload.get("items")
    count = payload.get("count") or 0
    return (items if isinstance(items, list) else []), int(count)


def _consultar_variante(
    options: DjenQueryOptions,
    *,
    numero_oab_variante: str | None,
) -> list[dict]:
    """Pagina uma única variante de OAB (ou consulta sem OAB) até esgotar `count`."""
    collected: list[dict] = []
    count: int | None = None
    retries_pagina = 0
    pagina = 1

    while pagina <= DJEN_MAX_PAGINAS:
        page_items, page_count = _fetch_pagina(
            options,
            numero_oab_variante=numero_oab_variante,
            pagina=pagina,
        )
        if count is None:
            count = page_count

        if not page_items:
            if len(collected) >= count:
                break
            if retries_pagina >= DJEN_MAX_RETRIES_PAGINA:
                break
            retries_pagina += 1
            time.sleep(DJEN_RETRY_DELAY_SECONDS * retries_pagina)
            continue

        retries_pagina = 0
        collected.extend(page_items)
        if len(collected) >= count:
            break
        pagina += 1

    return collected


def consultar_intimacoes(options: DjenQueryOptions) -> list[Intimacao]:
    """Consulta o DJEN e retorna as intimações (deduplicadas por id).

    Quando `numero_oab` é informado, consulta as variantes de sufixo
    conhecidas (`""`, `-O`, `-A`...), pois o filtro é comparado como string
    exata e cada tribunal grava a inscrição de um jeito diferente.
    """
    variantes = OAB_SUFIXOS if options.numero_oab else (None,)
    raw_by_id: dict[int, dict] = {}

    for sufixo in variantes:
        numero_oab_variante = f"{options.numero_oab}{sufixo}" if sufixo is not None else None
        for raw_item in _consultar_variante(
            options,
            numero_oab_variante=numero_oab_variante,
        ):
            item_id = raw_item.get("id")
            if item_id is None:
                continue
            existing = raw_by_id.get(int(item_id))
            # Tribunais podem cancelar publicações depois de emiti-las; a versão
            # com `motivo_cancelamento` preenchido é a mais recente e prevalece.
            if existing is None or raw_item.get("motivo_cancelamento"):
                raw_by_id[int(item_id)] = raw_item
        if sufixo:
            time.sleep(DJEN_RETRY_DELAY_SECONDS / 2)

    intimacoes = [parse_comunicacao_item(raw) for raw in raw_by_id.values()]
    return sorted(
        (intimacao for intimacao in intimacoes if intimacao is not None),
        key=lambda intimacao: intimacao.id,
    )
