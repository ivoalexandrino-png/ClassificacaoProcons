"""Núcleo de análise do radar: transforma um snapshot em editais relevantes.

100% offline e determinístico. Um edital é relevante quando toca ao menos uma
das áreas de interesse (por padrão: Direito, Saúde, Administração, Educação). As
áreas do edital vêm do coletor, mas são recalculadas a partir do título/resumo
quando ausentes (ex.: snapshot injetado por JSON). Editais encerrados são
descartados por padrão — o radar avisa sobre oportunidades ainda aproveitáveis.
"""

from __future__ import annotations

from classificacao_procons.radar.models import (
    ACTIONABLE_STATUSES,
    CORE_AREAS,
    Area,
    Edital,
    RadarAnalysis,
    RadarMatch,
    RadarSnapshot,
)
from classificacao_procons.radar.parser import classify_areas, fold

_STATUS_ORDER = {"aberto": 0, "previsto": 1, "desconhecido": 2, "encerrado": 3}


def _slug(value: str) -> str:
    return "-".join(fold(value).split())[:80]


def dedup_key_for(edital: Edital) -> str:
    """Chave estável de deduplicação para um edital.

    Preferimos ``raw_id``/URL; sem eles, caímos no par fonte+título normalizado.
    """
    base = edital.raw_id or edital.url
    if base:
        return f"{edital.source_key}:{base.strip()}"
    return f"{edital.source_key}:{_slug(edital.title)}"


def relevant_areas(edital: Edital, interest_areas: tuple[Area, ...]) -> tuple[Area, ...]:
    """Áreas de interesse tocadas pelo edital (0, 1 ou mais).

    Combina as áreas já atribuídas pelo coletor com as detectadas no título e
    resumo, preservando a ordem canônica de ``interest_areas``.
    """
    detected = set(edital.areas) | set(classify_areas(edital.title, edital.summary))
    return tuple(area for area in interest_areas if area in detected)


def analyze_snapshot(
    snapshot: RadarSnapshot,
    *,
    interest_areas: tuple[Area, ...] = CORE_AREAS,
    include_closed: bool = False,
) -> RadarAnalysis:
    """Seleciona os editais relevantes e os ordena por prioridade."""
    matches: list[RadarMatch] = []
    for edital in snapshot.editais:
        if not include_closed and edital.status not in ACTIONABLE_STATUSES:
            continue
        areas = relevant_areas(edital, interest_areas)
        if not areas:
            continue
        matches.append(
            RadarMatch(
                edital=edital,
                matched_areas=areas,
                scope=edital.scope,
                status=edital.status,
                dedup_key=dedup_key_for(edital),
            ),
        )

    matches.sort(
        key=lambda match: (
            _STATUS_ORDER.get(match.status, 9),
            match.edital.source_name,
            match.edital.title,
        ),
    )
    return RadarAnalysis(
        snapshot=snapshot,
        matches=tuple(matches),
        interest_areas=interest_areas,
    )
