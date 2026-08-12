"""Testes de agregação por processo e parsing KPI."""

from decimal import Decimal

from classificacao_procons.juridico.casos_consumidor.aggregate import build_process_rows
from classificacao_procons.juridico.casos_consumidor.models import CaseTheme, ConsumerCaseInsight
from classificacao_procons.juridico.casos_consumidor.monday_kpi import _parse_money


def test_parse_money_brl() -> None:
    assert _parse_money("R$ 1.893,21") == Decimal("1893.21")
    assert _parse_money("2500,00") == Decimal("2500.00")


def test_build_process_rows_groups_deposits_by_cnj(tmp_path) -> None:
    deposits = {
        "records": [
            {
                "consumer_folder": "Maria",
                "process_number": "0822560-79.2025.8.19.0208",
                "amount_brl": "100.00",
            },
            {
                "consumer_folder": "Maria",
                "process_number": "0822560-79.2025.8.19.0208",
                "amount_brl": "50.00",
            },
        ],
    }
    path = tmp_path / "deposits.json"
    path.write_text(__import__("json").dumps(deposits), encoding="utf-8")
    cases = [
        ConsumerCaseInsight(
            consumer_folder="Maria",
            process_numbers=("0822560-79.2025.8.19.0208",),
            primary_theme=CaseTheme.PROBLEMA_ENTREGA,
            secondary_themes=(),
            theme_confidence="high",
            theme_evidence=None,
            total_judicial_deposits_brl=Decimal("150"),
            deposit_records_count=2,
            condemnation_amount_brl=None,
            has_sentence_pdf=False,
            complaint_excerpt=None,
        ),
    ]
    rows = build_process_rows(cases=cases, deposits_json_path=path, kpi_by_process={})
    assert len(rows) == 1
    assert rows[0].total_judicial_deposits_brl == Decimal("150.00")
    assert rows[0].deposit_line_count == 2
    assert rows[0].primary_theme == CaseTheme.PROBLEMA_ENTREGA
