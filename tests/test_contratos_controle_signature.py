"""Testes de signature.accepted e reconciliação do Controle Assinaturas."""

from unittest.mock import patch

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.autentique.webhook import AutentiqueWebhookEvent
from classificacao_procons.contratos.constants import (
    CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
    CONTROLE_STATUS_AGUARDANDO_OUTROS,
    CONTROLE_STATUS_ASSINADO,
    SIGNER_EMAIL_JAN,
    SIGNER_EMAIL_LUCIANO,
)
from classificacao_procons.contratos.controle_sync import (
    process_signature_accepted_webhook_event,
    reconcile_controle_item_from_document,
    sync_controle_from_autentique,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


def _jan_luciano_groups() -> dict[str, str]:
    return {
        "assinados": "group-assinados",
        "contratos pendentes de assinatura jan": "group-jan",
        "contratos pendentes de assinatura luciano": "group-luciano",
    }


def _document_jan_signed() -> AutentiqueDocumentSummary:
    return AutentiqueDocumentSummary(
        document_id="doc-jan-signed",
        name="Contrato B2B - Empresa X",
        created_at="2026-07-16",
        signed_pdf_url=None,
        signatures=(
            AutentiqueSigner(
                public_id="sig-jan",
                name="Jan",
                email=SIGNER_EMAIL_JAN,
                short_link="https://assina.ae/jan",
                signed_at="2026-07-16T10:00:00Z",
            ),
            AutentiqueSigner(
                public_id="sig-luc",
                name="Luciano",
                email=SIGNER_EMAIL_LUCIANO,
                short_link="https://assina.ae/luc",
                signed_at=None,
            ),
        ),
    )


class TestSignatureAccepted:
    @patch("classificacao_procons.contratos.controle_sync.update_controle_item_progress")
    @patch("classificacao_procons.contratos.controle_sync.fetch_document_summary")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.find_controle_items_by_autentique_id")
    def test_should_update_both_tracks_when_luciano_signs_first(
        self,
        find_items_mock,
        load_groups_mock,
        fetch_mock,
        update_mock,
    ) -> None:
        find_items_mock.return_value = (
            ControleAssinaturasItem(
                item_id="111",
                name="Contrato B2B - Empresa X",
                status=CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
                tipo="Contratos B2B",
                signature_link="Autentique ID: doc-jan-signed\ncontrole_track: jan",
                group_id="group-jan",
            ),
            ControleAssinaturasItem(
                item_id="222",
                name="Contrato B2B - Empresa X",
                status=CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
                tipo=None,
                signature_link="Autentique ID: doc-jan-signed\ncontrole_track: luciano",
                group_id="group-luciano",
            ),
        )
        fetch_mock.return_value = AutentiqueDocumentSummary(
            document_id="doc-jan-signed",
            name="Contrato B2B - Empresa X",
            created_at="2026-07-16",
            signed_pdf_url=None,
            signatures=(
                AutentiqueSigner(
                    public_id="sig-jan",
                    name="Jan",
                    email=SIGNER_EMAIL_JAN,
                    short_link="https://assina.ae/jan",
                    signed_at=None,
                ),
                AutentiqueSigner(
                    public_id="sig-luc",
                    name="Luciano",
                    email=SIGNER_EMAIL_LUCIANO,
                    short_link="https://assina.ae/luc",
                    signed_at="2026-07-16T10:00:00Z",
                ),
            ),
        )
        load_groups_mock.return_value = _jan_luciano_groups()

        result = process_signature_accepted_webhook_event(
            AutentiqueWebhookEvent(
                event_id="evt-1",
                event_type="signature.accepted",
                document_id="doc-jan-signed",
                document_name="Contrato B2B - Empresa X",
                signed_pdf_url=None,
            ),
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
        )

        assert result.updated is True
        assert result.status_label == CONTROLE_STATUS_AGUARDANDO_OUTROS
        assert update_mock.call_count == 2

    @patch("classificacao_procons.contratos.controle_sync.register_document_in_controle")
    @patch("classificacao_procons.contratos.controle_sync.find_controle_items_by_autentique_id")
    def test_should_register_when_item_missing(
        self,
        find_items_mock,
        register_mock,
    ) -> None:
        from classificacao_procons.contratos.controle_sync import ControleRegistrationResult

        find_items_mock.return_value = ()
        register_mock.return_value = ControleRegistrationResult(
            document_id="doc-new",
            document_name="Contrato novo",
            monday_item_id="222",
            monday_item_url=None,
            group_id="group-jan",
            status_label=CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
            tipo_filled=True,
        )

        result = process_signature_accepted_webhook_event(
            AutentiqueWebhookEvent(
                event_id="evt-2",
                event_type="signature.accepted",
                document_id="doc-new",
                document_name="Contrato novo",
                signed_pdf_url=None,
            ),
            monday_api_token="monday-token",
        )

        assert result.monday_item_id == "222"
        register_mock.assert_called_once()


class TestControleReconcile:
    @patch("classificacao_procons.contratos.controle_sync.update_controle_item_progress")
    def test_should_skip_when_item_already_assinado(self, update_mock) -> None:
        result = reconcile_controle_item_from_document(
            document=_document_jan_signed(),
            controle_item=ControleAssinaturasItem(
                item_id="111",
                name="Contrato",
                status=CONTROLE_STATUS_ASSINADO,
                tipo="Contratos B2B",
                signature_link=None,
                group_id="group-assinados",
            ),
            api_token="monday-token",
            groups=_jan_luciano_groups(),
        )

        assert result.skipped is True
        assert result.skip_reason == "already_assinado"
        update_mock.assert_not_called()

    @patch("classificacao_procons.contratos.controle_sync.update_controle_item_progress")
    def test_should_skip_when_document_fully_signed(self, update_mock) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-done",
            name="Contrato",
            created_at="2026-07-16",
            signed_pdf_url="https://example.com/signed.pdf",
            signatures=(),
        )
        result = reconcile_controle_item_from_document(
            document=document,
            controle_item=ControleAssinaturasItem(
                item_id="111",
                name="Contrato",
                status=CONTROLE_STATUS_AGUARDANDO_OUTROS,
                tipo="Contratos B2B",
                signature_link=None,
                group_id="group-luciano",
            ),
            api_token="monday-token",
            groups=_jan_luciano_groups(),
        )

        assert result.skipped is True
        assert result.skip_reason == "awaiting_document_finished"
        update_mock.assert_not_called()


class TestControleSyncUpdateExisting:
    @patch("classificacao_procons.contratos.controle_sync.ensure_controle_dual_tracks_for_document")
    @patch("classificacao_procons.contratos.controle_sync.auto_link_unambiguous_legacy_controle")
    @patch("classificacao_procons.contratos.controle_sync.find_controle_items_by_autentique_id")
    @patch("classificacao_procons.contratos.controle_sync.reconcile_controle_from_document")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_should_update_existing_items_during_sync(
        self,
        list_documents_mock,
        build_index_mock,
        load_groups_mock,
        reconcile_mock,
        find_items_mock,
        auto_link_mock,
        repair_mock,
    ) -> None:
        from classificacao_procons.contratos.controle_link_suggestions import LegacyAutoLinkResult

        auto_link_mock.return_value = LegacyAutoLinkResult(
            applied=0,
            would_apply=0,
            ambiguous_skipped=0,
            failed=0,
            dry_run=False,
            items=(),
        )
        document = _document_jan_signed()
        existing_item = ControleAssinaturasItem(
            item_id="111",
            name=document.name,
            status=CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
            tipo="Contratos B2B",
            signature_link="Autentique ID: doc-jan-signed",
            group_id="group-jan",
        )
        list_documents_mock.return_value = [document]
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset({"doc-jan-signed"}),
            exact_names=frozenset(),
            items_by_document_id=(("doc-jan-signed", existing_item),),
        )
        load_groups_mock.return_value = _jan_luciano_groups()
        find_items_mock.return_value = (existing_item,)
        from classificacao_procons.contratos.controle_sync import ControleReconcileResult

        reconcile_mock.return_value = ControleReconcileResult(
            document_id=document.document_id,
            document_name=document.name,
            monday_item_id="111",
            updated=True,
            skipped=False,
            group_id="group-luciano",
            status_label=CONTROLE_STATUS_AGUARDANDO_OUTROS,
        )

        result = sync_controle_from_autentique(
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
            dry_run=False,
            update_existing=True,
        )

        assert result.updated == 1
        assert result.created == 0
        reconcile_mock.assert_called_once()
