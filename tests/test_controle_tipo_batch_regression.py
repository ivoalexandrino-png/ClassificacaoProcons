"""Regressão: títulos reais/sintéticos com Tipo esperado (heurística, alta confiança)."""

import pytest

from classificacao_procons.contratos.constants import MONDAY_TIPO_RH
from classificacao_procons.contratos.controle_tipo import (
    classify_controle_tipo_heuristic,
    document_requires_pdf_analysis,
    resolve_controle_tipo_label,
)


@pytest.mark.parametrize(
    ("document_name", "expected_tipo"),
    [
        ("Pedido Brass Hill - Glam Nutri wiki- Junho_2026", "Pedidos Marcas Próprias"),
        ("NDA - Fornecedor XYZ", "NDA"),
        ("Termo de Rescisão - Karen Santos", MONDAY_TIPO_RH),
    ],
)
def test_should_resolve_tipo_without_pdf_only_for_trusted_titles(
    document_name: str,
    expected_tipo: str,
) -> None:
    assert (
        resolve_controle_tipo_label(document_name=document_name, min_confidence="medium")
        == expected_tipo
    )


@pytest.mark.parametrize(
    "document_name",
    [
        "4.1 - Minuta Contrato Parceria - B4A - GE Beauty",
        "Contrato Influencer - Theulyn Reis",
        "Fornecimento Exclusivo Marcas Próprias - Nobilis 2025",
    ],
)
def test_should_not_resolve_tipo_from_title_without_pdf(document_name: str) -> None:
    assert document_requires_pdf_analysis(document_name=document_name) is True
    assert (
        resolve_controle_tipo_label(document_name=document_name, min_confidence="medium")
        is None
    )


@pytest.mark.parametrize(
    ("document_name", "expected_tipo"),
    [
        ("Pedido Brass Hill - Glam Nutri wiki- Junho_2026", "Pedidos Marcas Próprias"),
        ("NDA - Fornecedor XYZ", "NDA"),
        ("4.1 - Minuta Contrato Parceria - B4A - GE Beauty", "Contratos B2B"),
        ("Termo de Rescisão - Karen Santos", MONDAY_TIPO_RH),
        ("1º TERMO ADITIVO - 4Equity x BVI-B4A SERVIÇOS x CODEMP 2025", "Contratos Societários"),
        ("Contrato Influencer - Theulyn Reis", "Contratos Influencers (Queens)"),
        ("Contrato Societário - Tokenização ativos", "Contratos Societários"),
        ("Minuta Contrato Parceria B2B - Brass Hill", "Contratos B2B"),
        ("Cessão onerosa de participação societária - HoldCo", "Contratos Societários"),
    ],
)
def test_should_classify_known_titles_with_high_confidence(
    document_name: str,
    expected_tipo: str,
) -> None:
    result = classify_controle_tipo_heuristic(document_name=document_name)
    assert result.monday_tipo == expected_tipo
    assert result.confidence in ("high", "medium")


@pytest.mark.parametrize(
    "document_name",
    [
        "Contrato Brass Hill - fornecimento produtos 2026",
        "Contrato de Prestação de Serviços - Debora Duarte Ribeiro",
        "Contrato de Prestação de Serviços - Jamil Wahid Bou Kar",
    ],
)
def test_should_require_pdf_for_ambiguous_titles(document_name: str) -> None:
    assert document_requires_pdf_analysis(document_name=document_name) is True
    assert (
        resolve_controle_tipo_label(document_name=document_name, min_confidence="medium")
        is None
    )


def test_should_resolve_none_for_procuracao() -> None:
    assert (
        resolve_controle_tipo_label(
            document_name="Procuração - Jan __ Carol - localiza",
            min_confidence="medium",
        )
        is None
    )
