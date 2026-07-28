"""Testes de sugestões de vínculo legado Controle ↔ Autentique."""

from unittest.mock import patch

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.controle_link_suggestions import (
    apply_controle_link_suggestion,
    suggest_legacy_controle_links,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


def _pending_doc(*, document_id: str, name: str) -> AutentiqueDocumentSummary:
    return AutentiqueDocumentSummary(
        document_id=document_id,
        name=name,
        created_at=None,
        signed_pdf_url=None,
        signatures=(
            AutentiqueSigner(
                public_id="s1",
                name="Jan",
                email="jan@example.com",
                short_link="https://assina.ae/x",
                signed_at=None,
            ),
        ),
    )


class TestSuggestLegacyControleLinks:
    def test_should_suggest_high_confidence_when_titles_match_exactly(self) -> None:
        title = "Contrato B2B - Empresa Alpha"
        legacy = ControleAssinaturasItem(
            item_id="mon-1",
            name=title,
            status="Aguardando Assinatura",
            tipo=None,
            signature_link="https://assina.ae/legado",
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset({title.casefold()}),
            all_items=(legacy,),
        )
        pending = _pending_doc(document_id="doc-uuid-1", name=title)

        suggestions = suggest_legacy_controle_links(
            index=index,
            pending_documents=(pending,),
        )

        assert len(suggestions) == 1
        assert suggestions[0].monday_item_id == "mon-1"
        assert suggestions[0].autentique_document_id == "doc-uuid-1"
        assert suggestions[0].match_reason == "exact_title"
        assert suggestions[0].confidence == "high"

    def test_should_not_suggest_when_monday_item_already_has_autentique_id(self) -> None:
        title = "Contrato B2B - Empresa Alpha"
        linked = ControleAssinaturasItem(
            item_id="mon-1",
            name=title,
            status="Aguardando Assinatura",
            tipo="Contratos B2B",
            signature_link="https://assina.ae/x\nAutentique ID: doc-existing",
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset({"doc-existing"}),
            exact_names=frozenset({title.casefold()}),
            items_by_document_id=(("doc-existing", linked),),
            all_items=(linked,),
        )
        pending = _pending_doc(document_id="doc-new", name=title)

        suggestions = suggest_legacy_controle_links(
            index=index,
            pending_documents=(pending,),
        )

        assert suggestions == ()

    def test_should_not_suggest_risotex_minuta_vs_b2b_title(self) -> None:
        legacy = ControleAssinaturasItem(
            item_id="mon-ris",
            name="Contrato - B2B - Risotex - LaboCortex - 23.07.2026",
            status="Aguardando Assinatura",
            tipo=None,
            signature_link="https://assina.ae/legado",
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset(),
            all_items=(legacy,),
        )
        pending = _pending_doc(
            document_id="doc-ris",
            name="Minuta Padrão Contrato Parceria - Risotex (1)",
        )

        suggestions = suggest_legacy_controle_links(
            index=index,
            pending_documents=(pending,),
        )

        assert suggestions == ()

    def test_should_skip_pending_document_already_indexed_by_id(self) -> None:
        title = "Contrato B2B - Empresa Alpha"
        existing = ControleAssinaturasItem(
            item_id="mon-2",
            name=title,
            status="Aguardando Assinatura",
            tipo="Contratos B2B",
            signature_link="Autentique ID: doc-1",
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset({"doc-1"}),
            exact_names=frozenset({title.casefold()}),
            items_by_document_id=(("doc-1", existing),),
            all_items=(existing,),
        )
        pending = _pending_doc(document_id="doc-1", name=title)

        suggestions = suggest_legacy_controle_links(
            index=index,
            pending_documents=(pending,),
        )

        assert suggestions == ()


class TestApplyControleLinkSuggestion:
    @patch(
        "classificacao_procons.contratos.monday_contracts.ensure_autentique_id_on_controle_items",
    )
    def test_should_link_mirror_items_with_same_normalized_title(
        self,
        ensure_mock,
    ) -> None:
        title = "Contrato B2B - Empresa Alpha"
        jan = ControleAssinaturasItem(
            item_id="jan-1",
            name=title,
            status="Aguardando Assinatura",
            tipo="Contratos B2B",
            signature_link="https://assina.ae/jan",
        )
        luciano = ControleAssinaturasItem(
            item_id="luc-1",
            name=f"{title} ",
            status="Aguardando Assinatura",
            tipo=None,
            signature_link="https://assina.ae/luc",
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset({title.casefold()}),
            all_items=(jan, luciano),
        )

        linked = apply_controle_link_suggestion(
            api_token="monday-token",
            monday_item_id="jan-1",
            document_id="doc-apply-1",
            index=index,
        )

        assert set(linked) == {"jan-1", "luc-1"}
        ensure_mock.assert_called_once()
        call_kwargs = ensure_mock.call_args.kwargs
        assert call_kwargs["api_token"] == "monday-token"
        assert call_kwargs["document_id"] == "doc-apply-1"
        assert {i.item_id for i in call_kwargs["items"]} == {"jan-1", "luc-1"}
