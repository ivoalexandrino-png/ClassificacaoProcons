"""Coleta de editais das fontes de fomento.

As funções de *parsing* (``parse_rss``, ``parse_html``) são puras e testáveis
offline: recebem o texto bruto (XML/HTML) e a fonte, e devolvem ``Edital``s. O
acesso à rede (``fetch_source``) é isolado e usa apenas a biblioteca padrão
(``urllib``), como em ``juridico/comunica.py``.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from datetime import UTC, datetime
from urllib.parse import urljoin
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from classificacao_procons.radar.models import Edital, FundingSource, RadarSnapshot
from classificacao_procons.radar.parser import (
    classify_areas,
    detect_scope,
    detect_status,
    looks_like_edital,
    parse_date,
)

REQUEST_TIMEOUT_SECONDS = 30
_USER_AGENT = "b4a-radar-editais/1.0 (+https://b4a.com)"

# Namespaces comuns em feeds Atom.
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class RadarFetchError(RuntimeError):
    """Erro ao acessar ou interpretar o feed de uma fonte de fomento."""


def _clean(value: str | None) -> str:
    return " ".join(value.split()) if value else ""


def _edital_from_parts(
    *,
    source: FundingSource,
    title: str,
    url: str,
    summary: str | None,
    published_at_raw: str | None,
) -> Edital:
    title = _clean(title)
    summary = _clean(summary) or None
    areas = classify_areas(title, summary)
    # Se a fonte é temática (ex.: NIH → saúde) e o texto não deu pistas, herda a
    # área da fonte (menos ``multidisciplinar``, que não é uma área do núcleo).
    if not areas:
        areas = tuple(area for area in source.areas if area != "multidisciplinar")
    scope = detect_scope(title, summary, default=source.scope)
    status = detect_status(title, summary)
    return Edital(
        source_key=source.key,
        source_name=source.name,
        title=title or "(sem título)",
        url=url or source.url,
        scope=scope,
        areas=areas,
        summary=summary,
        status=status,
        published_at=parse_date(published_at_raw),
        raw_id=url or None,
    )


def parse_rss(xml_text: str, source: FundingSource) -> list[Edital]:
    """Interpreta um feed RSS 2.0 ou Atom em uma lista de editais."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise RadarFetchError(f"Feed XML inválido de {source.key}: {exc}") from exc

    editais: list[Edital] = []

    # RSS 2.0: <rss><channel><item>...
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        summary = item.findtext("description")
        published = item.findtext("pubDate") or item.findtext("date")
        editais.append(
            _edital_from_parts(
                source=source,
                title=title,
                url=_clean(link),
                summary=summary,
                published_at_raw=published,
            ),
        )

    # Atom: <feed><entry>...
    for entry in root.iter(f"{_ATOM_NS}entry"):
        title = entry.findtext(f"{_ATOM_NS}title") or ""
        summary = entry.findtext(f"{_ATOM_NS}summary") or entry.findtext(f"{_ATOM_NS}content")
        published = entry.findtext(f"{_ATOM_NS}updated") or entry.findtext(f"{_ATOM_NS}published")
        link = ""
        for link_el in entry.findall(f"{_ATOM_NS}link"):
            href = link_el.get("href")
            if href and link_el.get("rel", "alternate") in ("alternate", ""):
                link = href
                break
        editais.append(
            _edital_from_parts(
                source=source,
                title=title,
                url=_clean(link),
                summary=summary,
                published_at_raw=published,
            ),
        )

    return editais


def parse_html(
    html_text: str,
    source: FundingSource,
    *,
    base_url: str | None = None,
) -> list[Edital]:
    """Extrai editais de uma página HTML de listagem de oportunidades.

    Heurística: cada link (``<a>``) cujo texto parece anunciar um edital/chamada
    vira um ``Edital``. Deduplica por URL para não repetir o mesmo link.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    base = base_url or source.resolved_feed_url
    editais: list[Edital] = []
    seen_urls: set[str] = set()

    for anchor in soup.find_all("a"):
        text = _clean(anchor.get_text())
        if not looks_like_edital(text):
            continue
        href = anchor.get("href") or ""
        absolute = urljoin(base, href) if href else source.url
        if absolute in seen_urls:
            continue
        seen_urls.add(absolute)
        editais.append(
            _edital_from_parts(
                source=source,
                title=text,
                url=absolute,
                summary=None,
                published_at_raw=None,
            ),
        )
    return editais


def parse_feed(text: str, source: FundingSource) -> list[Edital]:
    """Escolhe o parser conforme ``source.feed_type`` (rss/atom → XML; senão HTML)."""
    if source.feed_type in ("rss", "atom"):
        return parse_rss(text, source)
    return parse_html(text, source)


def _http_get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        raise RadarFetchError(f"Falha ao acessar {url}: {exc}") from exc


def fetch_source(source: FundingSource) -> list[Edital]:
    """Baixa e interpreta os editais de uma fonte (acesso à rede)."""
    text = _http_get(source.resolved_feed_url)
    return parse_feed(text, source)


def collect_snapshot(
    sources: tuple[FundingSource, ...],
    *,
    ignore_errors: bool = True,
) -> RadarSnapshot:
    """Coleta os editais de todas as fontes num único snapshot.

    Com ``ignore_errors`` (padrão), uma fonte que falhar é pulada — o radar não
    deve parar por causa de um único portal fora do ar.
    """
    editais: list[Edital] = []
    collected_keys: list[str] = []
    for source in sources:
        try:
            editais.extend(fetch_source(source))
            collected_keys.append(source.key)
        except RadarFetchError:
            if not ignore_errors:
                raise
    return RadarSnapshot(
        captured_at=datetime.now(UTC),
        editais=tuple(editais),
        sources=tuple(collected_keys),
    )
