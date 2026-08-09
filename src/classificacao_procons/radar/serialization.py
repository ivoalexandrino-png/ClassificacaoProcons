"""Conversão entre JSON e os modelos do radar (usado pelo CLI e testes)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from classificacao_procons.radar.models import (
    Area,
    Edital,
    EditalStatus,
    RadarAnalysis,
    RadarMatch,
    RadarSnapshot,
    Scope,
)
from classificacao_procons.radar.parser import parse_date

_VALID_AREAS = {"direito", "saude", "administracao", "educacao", "multidisciplinar", "outro"}
_VALID_SCOPES = {"nacional", "internacional"}
_VALID_STATUS = {"aberto", "previsto", "encerrado", "desconhecido"}


class SnapshotParseError(ValueError):
    """JSON de snapshot malformado."""


def _parse_captured_at(value: Any) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _coerce_areas(value: Any) -> tuple[Area, ...]:
    if not isinstance(value, list):
        return ()
    areas: list[Area] = []
    for item in value:
        text = str(item).strip().casefold()
        if text in _VALID_AREAS:
            areas.append(text)  # type: ignore[arg-type]
    return tuple(areas)


def _coerce_scope(value: Any, default: Scope = "nacional") -> Scope:
    text = str(value or "").strip().casefold()
    return text if text in _VALID_SCOPES else default  # type: ignore[return-value]


def _coerce_status(value: Any) -> EditalStatus:
    text = str(value or "").strip().casefold()
    return text if text in _VALID_STATUS else "desconhecido"  # type: ignore[return-value]


def edital_from_dict(data: dict[str, Any]) -> Edital:
    if not isinstance(data, dict):
        raise SnapshotParseError("Cada edital deve ser um objeto JSON.")
    return Edital(
        source_key=str(data.get("source_key") or "").strip() or "desconhecida",
        source_name=str(data.get("source_name") or data.get("source_key") or "").strip()
        or "Fonte desconhecida",
        title=str(data.get("title") or "").strip() or "(sem título)",
        url=str(data.get("url") or "").strip(),
        scope=_coerce_scope(data.get("scope")),
        areas=_coerce_areas(data.get("areas")),
        summary=(str(data["summary"]).strip() or None) if data.get("summary") else None,
        status=_coerce_status(data.get("status")),
        published_at=parse_date(data.get("published_at")),
        opens_at=parse_date(data.get("opens_at")),
        closes_at=parse_date(data.get("closes_at")),
        raw_id=(str(data["raw_id"]).strip() or None) if data.get("raw_id") else None,
    )


def snapshot_from_dict(data: dict[str, Any]) -> RadarSnapshot:
    """Constrói um ``RadarSnapshot`` a partir de um dict (JSON carregado)."""
    if not isinstance(data, dict):
        raise SnapshotParseError("Snapshot deve ser um objeto JSON.")
    editais_raw = data.get("editais", [])
    if not isinstance(editais_raw, list):
        raise SnapshotParseError("Campo 'editais' deve ser uma lista.")
    sources_raw = data.get("sources", [])
    sources = tuple(str(item) for item in sources_raw) if isinstance(sources_raw, list) else ()
    return RadarSnapshot(
        captured_at=_parse_captured_at(data.get("captured_at")),
        editais=tuple(edital_from_dict(item) for item in editais_raw),
        sources=sources,
    )


def edital_to_dict(edital: Edital) -> dict[str, Any]:
    return {
        "source_key": edital.source_key,
        "source_name": edital.source_name,
        "title": edital.title,
        "url": edital.url,
        "scope": edital.scope,
        "areas": list(edital.areas),
        "summary": edital.summary,
        "status": edital.status,
        "published_at": edital.published_at.isoformat() if edital.published_at else None,
        "opens_at": edital.opens_at.isoformat() if edital.opens_at else None,
        "closes_at": edital.closes_at.isoformat() if edital.closes_at else None,
        "raw_id": edital.raw_id,
    }


def match_to_dict(match: RadarMatch) -> dict[str, Any]:
    return {
        "title": match.edital.title,
        "source_key": match.edital.source_key,
        "source_name": match.edital.source_name,
        "url": match.edital.url,
        "scope": match.scope,
        "status": match.status,
        "matched_areas": list(match.matched_areas),
        "closes_at": match.edital.closes_at.isoformat() if match.edital.closes_at else None,
        "dedup_key": match.dedup_key,
    }


def analysis_to_dict(analysis: RadarAnalysis) -> dict[str, Any]:
    """Serializa a análise para JSON (saída do CLI)."""
    snapshot = analysis.snapshot
    return {
        "captured_at": snapshot.captured_at.isoformat(),
        "sources": list(snapshot.sources),
        "interest_areas": list(analysis.interest_areas),
        "has_matches": analysis.has_matches,
        "edital_count": len(snapshot.editais),
        "match_count": len(analysis.matches),
        "open_count": len(analysis.open_matches),
        "matches": [match_to_dict(match) for match in analysis.matches],
    }
