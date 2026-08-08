"""Testes de (de)serialização JSON do Questor."""

from datetime import date

import pytest

from classificacao_procons.questor.analise import analyze_snapshot
from classificacao_procons.questor.serialization import (
    SnapshotParseError,
    analysis_to_dict,
    snapshot_from_dict,
)


def test_snapshot_from_dict_should_build_models() -> None:
    data = {
        "empresa": "Beauty For All",
        "cnpj": "12.345.678/0001-99",
        "captured_at": "2026-08-08T09:00:00",
        "certidoes": [
            {
                "orgao": "Receita Federal / PGFN",
                "situacao": "Positiva",
                "data_validade": "07/08/2026",
            },
        ],
        "mensagens": [
            {
                "orgao": "e-CAC",
                "assunto": "Intimação",
                "lida": False,
                "prazo_ciencia": "01/08/2026",
            },
        ],
    }
    snapshot = snapshot_from_dict(data)
    assert snapshot.empresa == "Beauty For All"
    assert snapshot.cnpj == "12345678000199"
    assert snapshot.certidoes[0].situacao == "positiva"
    assert snapshot.certidoes[0].data_validade == date(2026, 8, 7)
    assert snapshot.mensagens[0].lida is False
    assert snapshot.mensagens[0].prazo_ciencia == date(2026, 8, 1)


def test_snapshot_from_dict_should_default_missing_fields() -> None:
    snapshot = snapshot_from_dict({})
    assert snapshot.certidoes == ()
    assert snapshot.mensagens == ()
    assert snapshot.captured_at is not None


@pytest.mark.parametrize("bad", [{"certidoes": "x"}, {"mensagens": 3}])
def test_snapshot_from_dict_should_reject_non_list_collections(bad: dict) -> None:
    with pytest.raises(SnapshotParseError):
        snapshot_from_dict(bad)


def test_analysis_to_dict_should_summarize_issues() -> None:
    snapshot = snapshot_from_dict(
        {
            "captured_at": "2026-08-08T09:00:00",
            "certidoes": [{"orgao": "FGTS/CRF", "situacao": "positiva"}],
        },
    )
    analysis = analyze_snapshot(snapshot, today=date(2026, 8, 8))
    payload = analysis_to_dict(analysis)
    assert payload["has_problems"] is True
    assert payload["issue_count"] == 1
    assert payload["critical_count"] == 1
    assert payload["issues"][0]["kind"] == "certidao_positiva"
