"""Testes de link canônico Autentique no Controle."""

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.controle_autentique_link import (
    autentique_ids_in_controle_link,
    pick_primary_autentique_document_id,
    rebuild_controle_signature_link_text,
)
from classificacao_procons.contratos.controle_reconcile import (
    find_monday_items_with_multiple_autentique_ids,
    find_monday_track_status_mismatch,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


class TestControleAutentiqueLink:
    def test_should_pick_rescisao_id_when_prestacao_on_same_item(self) -> None:
        rescisao_id = "22b0a230000000000000000000000001"
        prestacao_id = "e7150000000000000000000000000001"
        item_name = "Termo Rescisão CLT Matheus 05 2026"
        documents_by_id = {
            rescisao_id: AutentiqueDocumentSummary(
                document_id=rescisao_id,
                name=item_name,
                created_at=None,
                signed_pdf_url=None,
                signatures=(),
            ),
            prestacao_id: AutentiqueDocumentSummary(
                document_id=prestacao_id,
                name="Contrato Prestação de Serviços Matheus",
                created_at=None,
                signed_pdf_url=None,
                signatures=(),
            ),
        }

        picked = pick_primary_autentique_document_id(
            item_name=item_name,
            linked_ids=(prestacao_id, rescisao_id),
            documents_by_id=documents_by_id,
        )

        assert picked == rescisao_id

    def test_should_rebuild_link_with_single_id_and_preserve_track(self) -> None:
        previous = (
            "https://assina.ae/abc\n"
            "Autentique ID: aaa\n"
            "Autentique ID: bbb\n"
            "controle_track: luciano"
        )
        rebuilt = rebuild_controle_signature_link_text(
            previous_link=previous,
            document_id="bbb",
        )

        assert autentique_ids_in_controle_link(rebuilt) == ("bbb",)
        assert "controle_track: luciano" in rebuilt
        assert "https://assina.ae/abc" in rebuilt

    def test_should_use_primary_doc_for_track_mismatch_not_first_indexed_id(self) -> None:
        rescisao_id = "22b0a230000000000000000000000001"
        prestacao_id = "e7150000000000000000000000000001"
        item = ControleAssinaturasItem(
            item_id="12601732756",
            name="Termo Rescisão CLT 05 2026",
            status="Bloqueado - aguardando providencia",
            tipo=None,
            signature_link=(
                f"Autentique ID: {prestacao_id}\n"
                f"Autentique ID: {rescisao_id}\n"
                "controle_track: luciano"
            ),
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset({prestacao_id, rescisao_id}),
            exact_names=frozenset(),
            items_by_document_id=(
                (prestacao_id, item),
                (rescisao_id, item),
            ),
            all_items=(item,),
        )
        luciano = AutentiqueSigner(
            public_id="l1",
            name="Luciano",
            email="juridico@example.com",
            short_link="https://assina.ae/l",
            signed_at=None,
        )
        jan = AutentiqueSigner(
            public_id="j1",
            name="Jan",
            email="jan@example.com",
            short_link="https://assina.ae/j",
            signed_at=None,
        )
        documents_by_id = {
            rescisao_id: AutentiqueDocumentSummary(
                document_id=rescisao_id,
                name="Termo Rescisão CLT 05 2026",
                created_at=None,
                signed_pdf_url=None,
                signatures=(luciano, jan),
            ),
            prestacao_id: AutentiqueDocumentSummary(
                document_id=prestacao_id,
                name="Prestação de Serviços Matheus",
                created_at=None,
                signed_pdf_url="https://example.com/signed.pdf",
                signatures=(luciano, jan),
            ),
        }

        rows = find_monday_track_status_mismatch(
            index=index,
            documents_by_id=documents_by_id,
        )

        assert len(rows) == 1
        assert rows[0][2] == rescisao_id

    def test_should_list_items_with_multiple_autentique_ids(self) -> None:
        id_a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        id_b = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        item = ControleAssinaturasItem(
            item_id="1",
            name="X",
            status=None,
            tipo=None,
            signature_link=f"Autentique ID: {id_a}\nAutentique ID: {id_b}",
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset({id_a, id_b}),
            exact_names=frozenset(),
            all_items=(item,),
        )

        rows = find_monday_items_with_multiple_autentique_ids(index)

        assert rows == (("1", "X", (id_a, id_b)),)
