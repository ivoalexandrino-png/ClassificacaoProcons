"""Testes de escopo Jan/Luciano pendentes e versão de título."""

from classificacao_procons.contratos.controle_board_scope import (
    is_controle_pending_track_group_title,
)
from classificacao_procons.contratos.controle_dedup import (
    controle_names_likely_same_contract,
    normalized_controle_titles_equal,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


class TestControlePendingScope:
    def test_should_recognize_jan_and_luciano_pending_groups(self) -> None:
        assert is_controle_pending_track_group_title("Contratos Pendentes de Assinatura Jan")
        assert is_controle_pending_track_group_title("Contratos Pendentes de Assinatura Luciano")

    def test_should_not_treat_assinados_as_pending_track(self) -> None:
        assert is_controle_pending_track_group_title("Assinados") is False
        assert is_controle_pending_track_group_title("Recusado") is False
        assert is_controle_pending_track_group_title("Pendente Fornecedor") is False


class TestBrunoDistratoNewVersion:
    def test_should_treat_parenthetical_two_as_different_title(self) -> None:
        old = "Distrato Bruno Santos de Castro - 25.06.2026"
        new = "Distrato Bruno Santos de Castro - 25.06.2026 (2)"
        assert normalized_controle_titles_equal(old, new) is False
        assert controle_names_likely_same_contract(new, old) is False

    def test_should_not_fuzzy_match_distrato_to_rescisao_same_person(self) -> None:
        distrato = "Distrato Bruno Santos de Castro - 25.06.2026"
        rescisao = "Rescisão SOP 2024 - Bruno Santos de Castro - 25.06.2026 (1)"
        assert controle_names_likely_same_contract(distrato, rescisao) is False

    def test_should_not_fuzzy_match_rescisao_clt_to_prestacao_servicos_same_person(self) -> None:
        rescisao = "Termo de Rescisão CLT - Matheus de Lima Ramos 05 2026"
        prestacao = "Contrato de Prestação de Serviços - Matheus de Lima Ramos"
        assert controle_names_likely_same_contract(prestacao, rescisao) is False

    def test_index_should_not_match_new_version_against_pending_only_exact(self) -> None:
        pending = ControleAssinaturasItem(
            item_id="1",
            name="Distrato Bruno Santos de Castro - 25.06.2026",
            status="Aguardando Assinatura",
            tipo="RH",
            signature_link="Autentique ID: old",
        )
        assinados = ControleAssinaturasItem(
            item_id="2",
            name="Distrato Bruno Santos de Castro - 25.06.2026",
            status="Assinado",
            tipo=None,
            signature_link=None,
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset({"old"}),
            exact_names=frozenset({pending.name.casefold(), assinados.name.casefold()}),
            all_items=(pending, assinados),
            pending_track_items=(pending,),
        )

        class _Doc:
            document_id = "new-uuid"
            name = "Distrato Bruno Santos de Castro - 25.06.2026 (2)"

            def primary_signature_link(self) -> None:
                return None

        assert index.matches_document(_Doc()) is False
