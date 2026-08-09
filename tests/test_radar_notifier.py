"""Testes da montagem do digest de e-mail do radar."""

from datetime import date, datetime

from classificacao_procons.radar.analise import analyze_snapshot
from classificacao_procons.radar.models import Edital, RadarSnapshot
from classificacao_procons.radar.notifier import (
    build_digest_bodies,
    build_digest_email,
    build_digest_subject,
)


def _analysis():
    snapshot = RadarSnapshot(
        captured_at=datetime(2026, 8, 9, 9, 0),
        editais=(
            Edital(
                source_key="nih",
                source_name="NIH",
                title="Call for proposals: public health",
                url="https://grants.nih.gov/call-1",
                scope="internacional",
                areas=("saude",),
                status="aberto",
                closes_at=date(2026, 9, 30),
            ),
        ),
    )
    return analyze_snapshot(snapshot)


class TestDigest:
    def test_subject_should_mention_open_count(self) -> None:
        subject = build_digest_subject(_analysis())
        assert "aberto" in subject.casefold()

    def test_bodies_should_include_title_and_link(self) -> None:
        text, html = build_digest_bodies(_analysis())
        assert "public health" in text
        assert "https://grants.nih.gov/call-1" in text
        assert "grants.nih.gov/call-1" in html
        assert "30/09/2026" in text

    def test_build_email_sets_recipients(self) -> None:
        email = build_digest_email(_analysis(), to=["pesquisa@uni.br"], cc=["prppg@uni.br"])
        assert email.to == ("pesquisa@uni.br",)
        assert email.cc == ("prppg@uni.br",)
        assert email.subject.startswith("[Radar de Editais]")
