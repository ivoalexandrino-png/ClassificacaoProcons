"""Testes de deduplicação por nome no Controle Assinaturas."""

from classificacao_procons.contratos.controle_dedup import (
    controle_names_likely_same_contract,
    find_likely_name_matches,
    normalized_controle_titles_equal,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


class TestControleNameDedup:
    def test_should_match_exact_title_after_normalization(self) -> None:
        assert normalized_controle_titles_equal(
            "Contrato B2B - Empresa X (1)",
            "contrato b2b - empresa x",
        )

    def test_should_not_match_risotex_when_only_supplier_token_overlaps(self) -> None:
        """Minuta vs contrato B2B: mesmo fornecedor, títulos diferentes → não fundir."""
        monday_name = "Contrato - B2B - Risotex - LaboCortex - 23.07.2026"
        autentique_name = "Minuta Padrão Contrato Parceria - Risotex (1)"

        assert controle_names_likely_same_contract(autentique_name, monday_name) is False

    def test_should_not_match_brasshill_contracts_with_different_periods(self) -> None:
        assert (
            controle_names_likely_same_contract("202505_BrassHill", "202503_BrassHill") is False
        )
        assert (
            controle_names_likely_same_contract(
                "202512_BrassHill",
                "231113_BrassHill_Residual",
            )
            is False
        )

    def test_should_match_brass_hill_pedido_variants_same_month(self) -> None:
        a = "Pedido Brass Hill - ( intense, deo colônias, scrub) - jun_2026"
        b = "Aprovar Pedido Brass Hill - Glam Nutri wiki- Junho_2026 (copy)"
        c = "Pedido Brass Hill - ( intense, deo colônias, scrub) - jun_2026.docx"

        assert controle_names_likely_same_contract(a, b) is True
        assert controle_names_likely_same_contract(a, c) is True

    def test_should_not_match_brass_hill_pedidos_different_months(self) -> None:
        assert (
            controle_names_likely_same_contract(
                "Aprovar Pedido Brass Hill Abdofast",
                "Pedido Brass Hill - jun_2026",
            )
            is False
        )

    def test_should_match_when_one_title_is_long_substring_of_other(self) -> None:
        short = "Contrato B2B - Fornecedor XYZ"
        long = "Minuta Padrão - Contrato B2B - Fornecedor XYZ - assinatura"
        assert controle_names_likely_same_contract(short, long) is True

    def test_should_match_when_three_or_more_distinctive_tokens_overlap(self) -> None:
        assert (
            controle_names_likely_same_contract(
                "Contrato B2B - Risotex - LaboCortex - Projeto Alpha",
                "Aditivo Risotex LaboCortex Projeto Alpha",
            )
            is True
        )

    def test_should_not_match_unrelated_contracts(self) -> None:
        assert (
            controle_names_likely_same_contract(
                "Contrato B2B - Empresa Alpha",
                "Contrato B2B - Empresa Beta",
            )
            is False
        )

    def test_index_matches_document_by_exact_name_only_without_autentique_id(self) -> None:
        title = "Contrato - B2B - Risotex - LaboCortex - 23.07.2026"
        existing = ControleAssinaturasItem(
            item_id="99",
            name=title,
            status="Aguardando Assinatura",
            tipo="Contratos B2B",
            signature_link="https://assina.ae/legado",
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset({title.casefold()}),
            all_items=(existing,),
        )

        class _Doc:
            document_id = "new-autentique-uuid"
            name = title

            def primary_signature_link(self) -> None:
                return None

        assert index.matches_document(_Doc()) is True
        assert (
            find_likely_name_matches(
                document_name="Minuta Padrão Contrato Parceria - Risotex (1)",
                items=index.all_items,
            )
            == ()
        )
