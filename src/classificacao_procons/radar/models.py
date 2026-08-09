"""Modelos de domínio do Radar de editais de fomento."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

# Áreas de pesquisa cobertas pelo radar. ``multidisciplinar`` marca editais que
# atendem a mais de uma área ou fomento geral; ``outro`` é o descarte.
Area = Literal[
    "direito",
    "saude",
    "administracao",
    "educacao",
    "multidisciplinar",
    "outro",
]

# Áreas de interesse "reais" (as quatro pedidas pela universidade).
CORE_AREAS: tuple[Area, ...] = ("direito", "saude", "administracao", "educacao")

# Abrangência do fomento.
Scope = Literal["nacional", "internacional"]

# Situação de um edital/chamada.
EditalStatus = Literal["aberto", "previsto", "encerrado", "desconhecido"]

# Situações que representam uma oportunidade viável de submissão.
ACTIONABLE_STATUSES: frozenset[str] = frozenset({"aberto", "previsto", "desconhecido"})


@dataclass(frozen=True)
class FundingSource:
    """Uma fonte de fomento monitorada pelo radar.

    ``feed_url``/``feed_type`` apontam para o recurso lido pelo coletor. Quando o
    ``feed_url`` não é conhecido, o radar cai para a página inicial (``url``) e o
    endpoint precisa ser calibrado na primeira execução assistida — mesma
    convenção do scraper do Questor.
    """

    key: str
    name: str
    scope: Scope
    url: str
    areas: tuple[Area, ...] = ("multidisciplinar",)
    feed_url: str | None = None
    feed_type: Literal["rss", "atom", "html", "json"] = "html"
    enabled: bool = True

    @property
    def resolved_feed_url(self) -> str:
        return self.feed_url or self.url


@dataclass(frozen=True)
class Edital:
    """Um edital/chamada de fomento coletado de uma fonte."""

    source_key: str
    source_name: str
    title: str
    url: str
    scope: Scope = "nacional"
    areas: tuple[Area, ...] = ()
    summary: str | None = None
    status: EditalStatus = "desconhecido"
    published_at: date | None = None
    opens_at: date | None = None
    closes_at: date | None = None
    raw_id: str | None = None


@dataclass(frozen=True)
class RadarMatch:
    """Um edital considerado relevante para as áreas de interesse."""

    edital: Edital
    matched_areas: tuple[Area, ...]
    scope: Scope
    dedup_key: str
    status: EditalStatus = "desconhecido"


@dataclass(frozen=True)
class RadarSnapshot:
    """Retrato do radar num instante: editais coletados das fontes."""

    captured_at: datetime
    editais: tuple[Edital, ...] = ()
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class RadarAnalysis:
    """Resultado da análise de um snapshot do radar."""

    snapshot: RadarSnapshot
    matches: tuple[RadarMatch, ...] = field(default_factory=tuple)
    interest_areas: tuple[Area, ...] = CORE_AREAS

    @property
    def has_matches(self) -> bool:
        return bool(self.matches)

    @property
    def open_matches(self) -> tuple[RadarMatch, ...]:
        return tuple(match for match in self.matches if match.status == "aberto")
