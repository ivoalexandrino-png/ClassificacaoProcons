"""Testes de classificação temática e benchmark (offline)."""

from decimal import Decimal

from classificacao_procons.juridico.casos_consumidor.benchmark import benchmark_similar_cases
from classificacao_procons.juridico.casos_consumidor.models import CaseTheme, ConsumerCaseInsight
from classificacao_procons.juridico.casos_consumidor.sentence import (
    extract_condemnation_amount_from_sentence,
)
from classificacao_procons.juridico.casos_consumidor.themes import classify_theme_from_text


def test_classify_entrega_from_text() -> None:
    theme, secondary, confidence = classify_theme_from_text(
        "A consumidora não recebeu a caixa e o rastreio não atualiza.",
    )
    assert theme == CaseTheme.PROBLEMA_ENTREGA
    assert confidence in {"medium", "high"}
    assert secondary == ()


def test_classify_renovacao_automatica() -> None:
    theme, _, _ = classify_theme_from_text(
        "Cancelou a assinatura mas houve renovação automática e nova cobrança.",
    )
    assert theme in {CaseTheme.RENOVACAO_AUTOMATICA, CaseTheme.PROBLEMA_CANCELAMENTO}


def test_extract_condemnation_from_sentence_snippet() -> None:
    text = "Ante o exposto, julgo procedente o pedido e condeno a ré ao pagamento de R$ 2.500,00."
    assert extract_condemnation_amount_from_sentence(text) == Decimal("2500.00")


def test_benchmark_matches_same_theme() -> None:
    cases = [
        ConsumerCaseInsight(
            consumer_folder="A",
            process_numbers=(),
            primary_theme=CaseTheme.PROBLEMA_ENTREGA,
            secondary_themes=(),
            theme_confidence="high",
            theme_evidence=None,
            total_judicial_deposits_brl=Decimal("1000"),
            deposit_records_count=1,
            condemnation_amount_brl=None,
            has_sentence_pdf=False,
            complaint_excerpt=None,
        ),
        ConsumerCaseInsight(
            consumer_folder="B",
            process_numbers=(),
            primary_theme=CaseTheme.PROBLEMA_PAGAMENTO,
            secondary_themes=(),
            theme_confidence="high",
            theme_evidence=None,
            total_judicial_deposits_brl=Decimal("5000"),
            deposit_records_count=1,
            condemnation_amount_brl=None,
            has_sentence_pdf=False,
            complaint_excerpt=None,
        ),
    ]
    stats = benchmark_similar_cases(
        complaint_text="Produto não chegou na minha casa, problema na entrega.",
        cases=cases,
    )
    assert stats.matched_cases == 1
    assert stats.max_deposits_brl == Decimal("1000")
