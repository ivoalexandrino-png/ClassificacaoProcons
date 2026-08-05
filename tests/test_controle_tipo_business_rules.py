"""Regras de negócio acordadas para Tipo no Controle Assinaturas."""

from classificacao_procons.contratos.constants import MONDAY_CONTROLE_TIPO_LABELS
from classificacao_procons.contratos.controle_tipo import (
    classify_controle_tipo_heuristic,
    resolve_controle_tipo_label,
)


class TestControleTipoBusinessRules:
    def test_controle_tipo_labels_exclude_cambio(self) -> None:
        assert "Contratos de Câmbio" not in MONDAY_CONTROLE_TIPO_LABELS
        assert "Contratos B2B" in MONDAY_CONTROLE_TIPO_LABELS

    def test_should_classify_nobilis_fornecimento_exclusivo_as_b4a(self) -> None:
        name = "Fornecimento Exclusivo Marcas Próprias - Nobilis 2025"
        result = classify_controle_tipo_heuristic(document_name=name)
        assert result.monday_tipo == "Contratos B4A"

    def test_should_classify_four_equity_codemp_as_societario(self) -> None:
        name = "4Equity x BVI-B4A SERVIÇOS x CODEMP 2025"
        result = classify_controle_tipo_heuristic(document_name=name)
        assert result.monday_tipo == "Contratos Societários"

    def test_should_classify_cessao_espaco_purodigital_as_b4a(self) -> None:
        name = "02 - Contrato - Cessão onerosa espaço - Purodigital - R"
        result = classify_controle_tipo_heuristic(document_name=name)
        assert result.monday_tipo == "Contratos B4A"

    def test_should_classify_aditivo_korres_as_b2b(self) -> None:
        name = "Aditivo - Korres Bfluence - 21.07.2026.docx"
        result = classify_controle_tipo_heuristic(document_name=name)
        assert result.monday_tipo == "Contratos B2B"

    def test_should_omit_tipo_for_circularizacao_advogados(self) -> None:
        name = "Carta de Circularização - Advogados - Ub"
        assert resolve_controle_tipo_label(document_name=name, min_confidence="medium") is None

    def test_should_omit_tipo_for_requerimento_parcelamento(self) -> None:
        name = "REQUERIMENTO DE PARCELAMENTO"
        assert resolve_controle_tipo_label(document_name=name, min_confidence="medium") is None

    def test_should_classify_abelha_rainha_as_b2b(self) -> None:
        name = "260707 Abelha Rainha"
        result = classify_controle_tipo_heuristic(document_name=name)
        assert result.monday_tipo == "Contratos B2B"

    def test_should_require_pdf_for_contrato_pj_prestador_externo(self) -> None:
        name = "Contrato PJ - Prestador externo marketing"
        assert resolve_controle_tipo_label(document_name=name, min_confidence="medium") is None
