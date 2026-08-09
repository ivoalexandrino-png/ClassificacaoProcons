"""Testes de serialização JSON <-> modelos do radar."""

from datetime import date

import pytest

from classificacao_procons.radar.analise import analyze_snapshot
from classificacao_procons.radar.serialization import (
    SnapshotParseError,
    analysis_to_dict,
    edital_to_dict,
    snapshot_from_dict,
)


def _snapshot_dict() -> dict:
    return {
        "captured_at": "2026-08-09T09:00:00",
        "sources": ["cnpq"],
        "editais": [
            {
                "source_key": "cnpq",
                "source_name": "CNPq",
                "title": "Edital de pesquisa em Direito",
                "url": "https://cnpq.br/edital-1",
                "scope": "nacional",
                "areas": ["direito"],
                "status": "aberto",
                "closes_at": "30/09/2026",
            },
        ],
    }


class TestSnapshotFromDict:
    def test_should_build_snapshot(self) -> None:
        snapshot = snapshot_from_dict(_snapshot_dict())
        assert len(snapshot.editais) == 1
        edital = snapshot.editais[0]
        assert edital.status == "aberto"
        assert edital.areas == ("direito",)
        assert edital.closes_at == date(2026, 9, 30)

    def test_should_default_unknown_status(self) -> None:
        data = _snapshot_dict()
        data["editais"][0]["status"] = "qualquer"
        snapshot = snapshot_from_dict(data)
        assert snapshot.editais[0].status == "desconhecido"

    def test_should_reject_non_object(self) -> None:
        with pytest.raises(SnapshotParseError):
            snapshot_from_dict([])  # type: ignore[arg-type]

    def test_should_reject_non_list_editais(self) -> None:
        with pytest.raises(SnapshotParseError):
            snapshot_from_dict({"editais": {}})


class TestSerializeOut:
    def test_edital_to_dict_roundtrip_fields(self) -> None:
        snapshot = snapshot_from_dict(_snapshot_dict())
        data = edital_to_dict(snapshot.editais[0])
        assert data["title"] == "Edital de pesquisa em Direito"
        assert data["closes_at"] == "2026-09-30"

    def test_analysis_to_dict(self) -> None:
        snapshot = snapshot_from_dict(_snapshot_dict())
        analysis = analyze_snapshot(snapshot)
        data = analysis_to_dict(analysis)
        assert data["match_count"] == 1
        assert data["open_count"] == 1
        assert data["matches"][0]["matched_areas"] == ["direito"]
