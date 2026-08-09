"""Testes do parsing de feeds RSS/Atom/HTML do radar (offline)."""

import pytest

from classificacao_procons.radar.feeds import (
    RadarFetchError,
    collect_snapshot,
    parse_html,
    parse_rss,
)
from classificacao_procons.radar.models import FundingSource

_SOURCE = FundingSource(
    key="cnpq",
    name="CNPq",
    scope="nacional",
    url="https://cnpq.br/",
    areas=("multidisciplinar",),
)

_HEALTH_SOURCE = FundingSource(
    key="nih",
    name="NIH",
    scope="internacional",
    url="https://grants.nih.gov/",
    areas=("saude",),
)


class TestParseRss:
    def test_should_parse_rss_items(self) -> None:
        xml = """<?xml version='1.0'?>
        <rss version='2.0'><channel>
          <item>
            <title>Edital de pesquisa em Direito e Educação</title>
            <link>https://cnpq.br/edital-1</link>
            <description>Inscrições abertas</description>
            <pubDate>Sat, 09 Aug 2026 10:00:00 +0000</pubDate>
          </item>
        </channel></rss>"""
        editais = parse_rss(xml, _SOURCE)
        assert len(editais) == 1
        assert editais[0].url == "https://cnpq.br/edital-1"
        assert editais[0].status == "aberto"
        assert set(editais[0].areas) == {"direito", "educacao"}
        assert editais[0].published_at is not None

    def test_should_parse_atom_entries(self) -> None:
        xml = """<?xml version='1.0'?>
        <feed xmlns='http://www.w3.org/2005/Atom'>
          <entry>
            <title>Call for proposals: public health</title>
            <link rel='alternate' href='https://grants.nih.gov/call-1'/>
            <summary>Now open</summary>
            <updated>2026-08-09T10:00:00Z</updated>
          </entry>
        </feed>"""
        editais = parse_rss(xml, _HEALTH_SOURCE)
        assert len(editais) == 1
        assert editais[0].url == "https://grants.nih.gov/call-1"
        assert editais[0].areas == ("saude",)

    def test_should_inherit_area_from_source_when_text_is_vague(self) -> None:
        xml = """<?xml version='1.0'?>
        <rss version='2.0'><channel>
          <item><title>Funding opportunity 01/2026</title>
          <link>https://grants.nih.gov/x</link></item>
        </channel></rss>"""
        editais = parse_rss(xml, _HEALTH_SOURCE)
        assert editais[0].areas == ("saude",)

    def test_should_raise_on_invalid_xml(self) -> None:
        with pytest.raises(RadarFetchError):
            parse_rss("<not-xml", _SOURCE)


class TestParseHtml:
    def test_should_extract_edital_links(self) -> None:
        html = """
        <html><body>
          <a href='/editais/1'>Edital 01/2026 - bolsas em saúde</a>
          <a href='/sobre'>Sobre nós</a>
          <a href='https://x/2'>Chamada pública de educação</a>
        </body></html>"""
        editais = parse_html(html, _SOURCE, base_url="https://cnpq.br/")
        urls = {edital.url for edital in editais}
        assert urls == {"https://cnpq.br/editais/1", "https://x/2"}

    def test_should_deduplicate_same_url(self) -> None:
        html = """
        <a href='/e/1'>Edital de saúde</a>
        <a href='/e/1'>Edital de saúde (repetido)</a>"""
        editais = parse_html(html, _SOURCE, base_url="https://cnpq.br/")
        assert len(editais) == 1


class TestCollectSnapshot:
    def test_should_skip_failing_sources_when_ignoring_errors(self, monkeypatch) -> None:
        def _boom(source):
            raise RadarFetchError("down")

        monkeypatch.setattr("classificacao_procons.radar.feeds.fetch_source", _boom)
        snapshot = collect_snapshot((_SOURCE,), ignore_errors=True)
        assert snapshot.editais == ()
        assert snapshot.sources == ()

    def test_should_raise_when_not_ignoring_errors(self, monkeypatch) -> None:
        def _boom(source):
            raise RadarFetchError("down")

        monkeypatch.setattr("classificacao_procons.radar.feeds.fetch_source", _boom)
        with pytest.raises(RadarFetchError):
            collect_snapshot((_SOURCE,), ignore_errors=False)

    def test_should_aggregate_editais_from_sources(self, monkeypatch) -> None:
        from classificacao_procons.radar.models import Edital

        def _fake(source):
            return [
                Edital(
                    source_key=source.key,
                    source_name=source.name,
                    title="Edital de direito",
                    url="https://x/1",
                    areas=("direito",),
                ),
            ]

        monkeypatch.setattr("classificacao_procons.radar.feeds.fetch_source", _fake)
        snapshot = collect_snapshot((_SOURCE,))
        assert len(snapshot.editais) == 1
        assert snapshot.sources == ("cnpq",)
