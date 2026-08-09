"""Testes do plano Autentique → Controle (classificar antes de criar)."""

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.constants import CONTROLE_STATUS_ASSINADO
from classificacao_procons.contratos.controle_autentique_plan import (
    ControlePlanAction,
    build_controle_autentique_plan,
    classify_autentique_document_for_controle,
    plan_action_counts,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


def _signed_doc() -> AutentiqueDocumentSummary:
    return AutentiqueDocumentSummary(
        document_id="doc-signed-1",
        name="Contrato B2B - Legado",
        created_at="2026-01-01",
        signed_pdf_url="https://example.com/s.pdf",
        signatures=(
            AutentiqueSigner(
                public_id="s1",
                name="Jan",
                email="jan@example.com",
                short_link="https://assina.ae/x",
                signed_at="2026-01-01T00:00:00Z",
            ),
        ),
    )


def _pending_doc() -> AutentiqueDocumentSummary:
    return AutentiqueDocumentSummary(
        document_id="doc-pending-1",
        name="Contrato pendente novo",
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


class TestControleAutentiquePlan:
    def test_should_classify_vincular_when_legacy_assinado_without_id(self) -> None:
        title = "Contrato B2B - Legado"
        legacy = ControleAssinaturasItem(
            item_id="legacy-jan",
            name=title,
            status=CONTROLE_STATUS_ASSINADO,
            tipo="Contratos B2B",
            signature_link="https://assina.ae/old",
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset({title.casefold()}),
            all_items=(legacy,),
        )
        row = classify_autentique_document_for_controle(
            document=_signed_doc(),
            index=index,
        )
        assert row.action == ControlePlanAction.VINCULAR
        assert row.monday_item_ids == ("legacy-jan",)

    def test_should_classify_vincular_jan_and_luciano_tracks_without_id(self) -> None:
        title = "Contrato B2B - Legado"
        jan = ControleAssinaturasItem(
            item_id="jan-1",
            name=title,
            status="Aguardando Assinatura",
            tipo="Contratos B2B",
            signature_link=None,
            group_id="group-jan",
        )
        luciano = ControleAssinaturasItem(
            item_id="luc-1",
            name=title,
            status="Aguardando Assinatura",
            tipo=None,
            signature_link=None,
            group_id="group-luciano",
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset({title.casefold()}),
            all_items=(jan, luciano),
        )
        pending = AutentiqueDocumentSummary(
            document_id="doc-pending-1",
            name=title,
            created_at=None,
            signed_pdf_url=None,
            signatures=_pending_doc().signatures,
        )
        row = classify_autentique_document_for_controle(
            document=pending,
            index=index,
        )
        assert row.action == ControlePlanAction.VINCULAR
        assert set(row.monday_item_ids) == {"jan-1", "luc-1"}

    def test_should_classify_atualizar_when_autentique_id_on_monday(self) -> None:
        document = _signed_doc()
        linked = ControleAssinaturasItem(
            item_id="111",
            name=document.name,
            status=CONTROLE_STATUS_ASSINADO,
            tipo="Contratos B2B",
            signature_link="Autentique ID: doc-signed-1",
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset({"doc-signed-1"}),
            exact_names=frozenset(),
            items_by_document_id=(("doc-signed-1", linked),),
            all_items=(linked,),
        )
        row = classify_autentique_document_for_controle(document=document, index=index)
        assert row.action == ControlePlanAction.ATUALIZAR

    def test_should_ignore_signed_without_legacy_instead_of_criar(self) -> None:
        index = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset(),
            all_items=(),
        )
        row = classify_autentique_document_for_controle(
            document=_signed_doc(),
            index=index,
        )
        assert row.action == ControlePlanAction.IGNORAR
        assert row.reason == "signed_no_matching_legacy_row"

    def test_should_criar_only_pending_without_monday_row(self) -> None:
        index = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset(),
            all_items=(),
        )
        row = classify_autentique_document_for_controle(
            document=_pending_doc(),
            index=index,
        )
        assert row.action == ControlePlanAction.CRIAR

    def test_should_ignore_when_monday_already_has_assinado_same_title(self) -> None:
        title = "Declaração de Férias Antecipadas - Larissa Araújo Nascimento"
        legacy = ControleAssinaturasItem(
            item_id="legacy-1",
            name=title,
            status=CONTROLE_STATUS_ASSINADO,
            tipo=None,
            signature_link="Autentique ID: old-other-doc",
        )
        document = AutentiqueDocumentSummary(
            document_id="new-signed-doc",
            name=title,
            created_at=None,
            signed_pdf_url="https://example.com/signed.pdf",
            signatures=(
                AutentiqueSigner(
                    public_id="s1",
                    name="Larissa",
                    email="l@example.com",
                    short_link=None,
                    signed_at="2026-01-01T00:00:00Z",
                ),
            ),
        )
        index = ControleAssinaturasIndex(
            document_ids=frozenset({"old-other-doc"}),
            exact_names=frozenset({title.casefold()}),
            all_items=(legacy,),
        )
        row = classify_autentique_document_for_controle(document=document, index=index)
        assert row.action == ControlePlanAction.IGNORAR
        assert row.reason == "monday_assinado_same_title_do_not_create"

    def test_should_build_plan_counts(self) -> None:
        index = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset(),
            all_items=(),
        )
        rows = build_controle_autentique_plan(
            documents=(_pending_doc(), _signed_doc()),
            index=index,
        )
        counts = plan_action_counts(rows)
        assert counts["criar"] == 1
        assert counts["ignorar"] == 1
