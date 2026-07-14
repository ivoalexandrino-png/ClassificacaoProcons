"""Testes de extração de dados do portal."""

from classificacao_procons.portal.client import _complaint_details, _labeled_value, _normalize_cpf

SAMPLE_PAGE_LINES = [
    "Protocolo",
    "1653213/2026",
    "Data da solicitação",
    "14/07/2026",
    "Prazo",
    "24/07/2026",
    "Classificação",
    "Não entrega / demora na entrega",
    "CPF",
    "458.262.368-92",
    "Nome completo",
    "JANIS LEAO PALOSQUE GARUZI",
    "Reclamação",
    "Detalhes",
    "Produto não chegou no prazo.",
    "Pedido",
    "Entrega imediata",
]


class TestPortalExtraction:
    def test_should_extract_labeled_values(self) -> None:
        assert _labeled_value(SAMPLE_PAGE_LINES, "Protocolo") == "1653213/2026"
        assert _labeled_value(SAMPLE_PAGE_LINES, "Nome completo") == "JANIS LEAO PALOSQUE GARUZI"

    def test_should_normalize_cpf_without_punctuation(self) -> None:
        assert _normalize_cpf("458.262.368-92") == "45826236892"

    def test_should_extract_complaint_details(self) -> None:
        assert _complaint_details(SAMPLE_PAGE_LINES) == "Produto não chegou no prazo."
