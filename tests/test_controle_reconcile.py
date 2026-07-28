"""Testes de análise de reconciliação Controle."""

from classificacao_procons.contratos.autentique.client import AutentiqueDocumentSummary
from classificacao_procons.contratos.controle_reconcile import (
    find_duplicate_autentique_ids,
    find_duplicate_normalized_names,
    find_monday_status_behind_autentique,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


class TestControleReconcileAnalysis:
    def test_should_detect_duplicate_autentique_ids(self) -> None:
        item_a = ControleAssinaturasItem(
            item_id="1",
            name="Contrato A",
            status=None,
            tipo=None,
            signature_link="Autentique ID: abc",
        )
        item_b = ControleAssinaturasItem(
            item_id="2",
            name="Contrato A cópia",
            status=None,
            tipo=None,
            signature_link="Autentique ID: abc",
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset({"abc"}),
            exact_names=frozenset(),
            items_by_document_id=(("abc", item_a), ("abc", item_b)),
            all_items=(item_a, item_b),
        )

        duplicates = find_duplicate_autentique_ids(index)

        assert duplicates == (("abc", ("1", "2")),)

    def test_should_detect_status_behind_autentique(self) -> None:
        item = ControleAssinaturasItem(
            item_id="10",
            name="Contrato",
            status="Aguardando Assinatura",
            tipo="Contratos B2B",
            signature_link="Autentique ID: doc-1",
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset({"doc-1"}),
            exact_names=frozenset(),
            items_by_document_id=(("doc-1", item),),
            all_items=(item,),
        )
        document = AutentiqueDocumentSummary(
            document_id="doc-1",
            name="Contrato",
            created_at=None,
            signed_pdf_url="https://example.com/s.pdf",
            signatures=(),
        )

        rows = find_monday_status_behind_autentique(
            index=index,
            documents_by_id={"doc-1": document},
        )

        assert len(rows) == 1
        assert rows[0][0] == "10"
        assert rows[0][4] == "Assinado"

    def test_should_detect_duplicate_normalized_names(self) -> None:
        item_a = ControleAssinaturasItem(
            item_id="1",
            name="Contrato X (1)",
            status=None,
            tipo=None,
            signature_link=None,
        )
        item_b = ControleAssinaturasItem(
            item_id="2",
            name="contrato x",
            status=None,
            tipo=None,
            signature_link=None,
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset(),
            all_items=(item_a, item_b),
        )

        dup_names = find_duplicate_normalized_names(index)

        assert len(dup_names) == 1
        assert len(dup_names[0][1]) == 2
