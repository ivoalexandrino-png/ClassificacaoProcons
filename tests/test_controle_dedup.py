"""Testes de deduplicação por nome no Controle Assinaturas."""

from classificacao_procons.contratos.controle_dedup import (
    controle_names_likely_same_contract,
    find_likely_name_matches,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


class TestControleNameDedup:
    def test_should_match_risotex_titles_from_monday_and_autentique(self) -> None:
        monday_name = "Contrato - B2B - Risotex - LaboCortex - 23.07.2026"
        autentique_name = "Minuta Padrão Contrato Parceria - Risotex (1)"

        assert controle_names_likely_same_contract(autentique_name, monday_name) is True

    def test_should_not_match_unrelated_contracts(self) -> None:
        assert (
            controle_names_likely_same_contract(
                "Contrato B2B - Empresa Alpha",
                "Contrato B2B - Empresa Beta",
            )
            is False
        )

    def test_index_matches_document_by_likely_name_without_autentique_id(self) -> None:
        existing = ControleAssinaturasItem(
            item_id="99",
            name="Contrato - B2B - Risotex - LaboCortex - 23.07.2026",
            status="Aguardando Assinatura",
            tipo="Contratos B2B",
            signature_link="https://assina.ae/legado",
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset({existing.name.casefold()}),
            all_items=(existing,),
        )

        class _Doc:
            document_id = "new-autentique-uuid"
            name = "Minuta Padrão Contrato Parceria - Risotex (1)"

            def primary_signature_link(self) -> None:
                return None

        assert index.matches_document(_Doc()) is True
        matches = find_likely_name_matches(document_name=_Doc.name, items=index.all_items)
        assert len(matches) == 1
        assert matches[0].item_id == "99"
