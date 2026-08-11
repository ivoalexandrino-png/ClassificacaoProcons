"""Entrypoints Autentique → Controle respeitam CONTROLE_WRITE_ENABLED=false."""

from unittest.mock import patch

import pytest

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.autentique.webhook import AutentiqueWebhookEvent
from classificacao_procons.contratos.constants import SIGNER_EMAIL_JAN, SIGNER_EMAIL_LUCIANO
from classificacao_procons.contratos.controle_sync import (
    compare_autentique_with_controle,
    process_document_created_webhook_event,
    process_signature_accepted_webhook_event,
    reconcile_controle_compare_mismatches,
    register_document_in_controle,
    repair_controle_canonical_autentique_links,
    sync_controle_from_autentique,
)
from classificacao_procons.contratos.controle_sync_remediation import (
    remediate_erroneous_sync_duplicates,
)
from classificacao_procons.contratos.controle_write_policy import (
    ENV_CONTROLE_WRITE_ENABLED,
    ControleWriteForbiddenError,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import (
    ControleAssinaturasIndex,
    update_controle_item_progress,
)


@pytest.fixture
def write_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_CONTROLE_WRITE_ENABLED, "false")
    monkeypatch.setenv("CONTROLE_PAUSE_CREATE", "true")


def _b2b_document(*, doc_id: str = "doc-new") -> AutentiqueDocumentSummary:
    return AutentiqueDocumentSummary(
        document_id=doc_id,
        name="Contrato B2B - Empresa X",
        created_at="2026-01-01",
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
                signed_at=None,
            ),
        ),
    )


class TestCompareWithWriteDisabled:
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_should_run_compare_when_write_disabled(
        self,
        list_documents_mock,
        build_index_mock,
        write_disabled: None,
    ) -> None:
        list_documents_mock.return_value = [_b2b_document()]
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset(),
        )

        result = compare_autentique_with_controle(
            monday_api_token="token",
            autentique_api_token="token",
        )

        assert result.autentique_total == 1


class TestMondayWritesBlocked:
    def test_update_progress_should_raise_when_write_disabled(
        self,
        write_disabled: None,
    ) -> None:
        with pytest.raises(ControleWriteForbiddenError):
            update_controle_item_progress(
                api_token="token",
                item_id="1",
                group_id="g",
                status_label="Aguardando Assinatura",
            )


class TestRegisterAndWebhooksBlocked:
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.fetch_document_summary")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.find_controle_items_by_autentique_id")
    def test_register_should_not_write_when_write_disabled(
        self,
        find_items_mock,
        load_groups_mock,
        fetch_mock,
        build_index_mock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(ENV_CONTROLE_WRITE_ENABLED, "false")
        monkeypatch.setenv("CONTROLE_PAUSE_CREATE", "false")
        find_items_mock.return_value = ()
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset(),
        )
        fetch_mock.return_value = _b2b_document(doc_id="doc-paused")
        load_groups_mock.return_value = {
            "assinados": "g-assinados",
            "contratos pendentes de assinatura jan": "g-jan",
            "contratos pendentes de assinatura luciano": "g-luciano",
        }

        with pytest.raises(ControleWriteForbiddenError):
            register_document_in_controle(
                document_id="doc-paused",
                monday_api_token="monday-token",
            )

    @patch("classificacao_procons.contratos.controle_sync.register_document_in_controle")
    @patch("classificacao_procons.contratos.controle_sync.find_controle_items_by_autentique_id")
    def test_document_created_should_delegate_to_register(
        self,
        find_items_mock,
        register_mock,
        write_disabled: None,
    ) -> None:
        find_items_mock.return_value = ()
        register_mock.side_effect = ControleWriteForbiddenError("blocked")

        with pytest.raises(ControleWriteForbiddenError):
            process_document_created_webhook_event(
                AutentiqueWebhookEvent(
                    event_id="e1",
                    event_type="document.created",
                    document_id="doc-1",
                    document_name="Contrato B2B - X",
                    signed_pdf_url=None,
                ),
                monday_api_token="token",
            )

    @patch("classificacao_procons.contratos.controle_sync.fetch_document_summary")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.find_controle_items_by_autentique_id")
    def test_signature_accepted_should_not_update_when_write_disabled(
        self,
        find_items_mock,
        load_groups_mock,
        fetch_mock,
        write_disabled: None,
    ) -> None:
        find_items_mock.return_value = (
            ControleAssinaturasItem(
                item_id="111",
                name="Contrato B2B - Empresa X",
                status="Aguardando Assinatura",
                tipo="B2B",
                signature_link="Autentique ID: doc-new\ncontrole_track: jan",
                group_id="g-jan",
            ),
        )
        fetch_mock.return_value = _b2b_document()
        load_groups_mock.return_value = {
            "assinados": "g-assinados",
            "contratos pendentes de assinatura jan": "g-jan",
            "contratos pendentes de assinatura luciano": "g-luciano",
        }

        with pytest.raises(ControleWriteForbiddenError):
            process_signature_accepted_webhook_event(
                AutentiqueWebhookEvent(
                    event_id="e2",
                    event_type="signature.accepted",
                    document_id="doc-new",
                    document_name="Contrato B2B - Empresa X",
                    signed_pdf_url=None,
                ),
                monday_api_token="monday-token",
            )


class TestSyncRepairReconcileRemediationBlocked:
    @patch("classificacao_procons.contratos.controle_sync.auto_link_unambiguous_legacy_controle")
    @patch("classificacao_procons.contratos.controle_sync.find_controle_items_by_autentique_id")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_sync_should_allow_dry_run_when_write_disabled(
        self,
        list_documents_mock,
        build_index_mock,
        load_groups_mock,
        find_items_mock,
        auto_link_mock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from classificacao_procons.contratos.controle_link_suggestions import LegacyAutoLinkResult

        monkeypatch.setenv(ENV_CONTROLE_WRITE_ENABLED, "false")
        find_items_mock.return_value = ()
        auto_link_mock.return_value = LegacyAutoLinkResult(
            applied=0,
            would_apply=0,
            ambiguous_skipped=0,
            failed=0,
            dry_run=False,
            items=(),
        )
        list_documents_mock.return_value = [_b2b_document()]
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset(),
        )
        load_groups_mock.return_value = {
            "assinados": "g-assinados",
            "contratos pendentes de assinatura jan": "g-jan",
            "contratos pendentes de assinatura luciano": "g-luciano",
        }

        result = sync_controle_from_autentique(
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
            dry_run=True,
        )

        assert result.dry_run is True
        assert result.total_autentique == 1

    @patch("classificacao_procons.contratos.controle_sync.auto_link_unambiguous_legacy_controle")
    @patch("classificacao_procons.contratos.controle_sync.find_controle_items_by_autentique_id")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_sync_should_not_create_when_write_disabled(
        self,
        list_documents_mock,
        build_index_mock,
        load_groups_mock,
        find_items_mock,
        auto_link_mock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from classificacao_procons.contratos.controle_link_suggestions import LegacyAutoLinkResult

        monkeypatch.setenv(ENV_CONTROLE_WRITE_ENABLED, "false")
        monkeypatch.setenv("CONTROLE_PAUSE_CREATE", "false")
        find_items_mock.return_value = ()
        auto_link_mock.return_value = LegacyAutoLinkResult(
            applied=0,
            would_apply=0,
            ambiguous_skipped=0,
            failed=0,
            dry_run=False,
            items=(),
        )
        list_documents_mock.return_value = [_b2b_document()]
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset(),
        )
        load_groups_mock.return_value = {
            "assinados": "g-assinados",
            "contratos pendentes de assinatura jan": "g-jan",
            "contratos pendentes de assinatura luciano": "g-luciano",
        }

        with pytest.raises(ControleWriteForbiddenError):
            sync_controle_from_autentique(
                monday_api_token="monday-token",
                autentique_api_token="autentique-token",
                dry_run=False,
                allow_create=True,
            )

    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_repair_should_not_write_when_write_disabled(
        self,
        list_documents_mock,
        build_index_mock,
        write_disabled: None,
    ) -> None:
        list_documents_mock.return_value = []
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset({"doc-1"}),
            exact_names=frozenset(),
            items_by_document_id=(
                (
                    "doc-1",
                    ControleAssinaturasItem(
                        item_id="1",
                        name="X",
                        status=None,
                        tipo=None,
                        signature_link="Autentique ID: doc-1\nAutentique ID: doc-2",
                    ),
                ),
            ),
            all_items=(
                ControleAssinaturasItem(
                    item_id="1",
                    name="X",
                    status=None,
                    tipo=None,
                    signature_link="Autentique ID: doc-1\nAutentique ID: doc-2",
                ),
            ),
        )

        with pytest.raises(ControleWriteForbiddenError):
            repair_controle_canonical_autentique_links(
                monday_api_token="token",
                dry_run=False,
            )

    @patch("classificacao_procons.contratos.controle_sync.build_controle_assinaturas_index")
    @patch("classificacao_procons.contratos.controle_sync.list_documents")
    def test_reconcile_should_not_write_when_write_disabled(
        self,
        list_documents_mock,
        build_index_mock,
        write_disabled: None,
    ) -> None:
        list_documents_mock.return_value = [_b2b_document(doc_id="doc-1")]
        item = ControleAssinaturasItem(
            item_id="1",
            name="Contrato B2B - Empresa X",
            status="Aguardando outros",
            tipo="B2B",
            signature_link="Autentique ID: doc-1\ncontrole_track: jan",
            group_id="g-jan",
        )
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset({"doc-1"}),
            exact_names=frozenset(),
            items_by_document_id=(("doc-1", item),),
            all_items=(item,),
        )

        with pytest.raises(ControleWriteForbiddenError):
            reconcile_controle_compare_mismatches(
                monday_api_token="token",
                dry_run=False,
            )

    @patch("classificacao_procons.contratos.controle_sync_remediation.build_controle_assinaturas_index")
    def test_remediation_should_not_archive_when_write_disabled(
        self,
        build_index_mock,
        write_disabled: None,
    ) -> None:
        build_index_mock.return_value = ControleAssinaturasIndex(
            document_ids=frozenset(),
            exact_names=frozenset(),
            all_items=(),
        )

        with pytest.raises(ControleWriteForbiddenError):
            remediate_erroneous_sync_duplicates(
                monday_api_token="token",
                dry_run=False,
            )
