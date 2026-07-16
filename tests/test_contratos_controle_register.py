"""Testes de registro automático no Controle Assinaturas."""

from unittest.mock import patch

from classificacao_procons.contratos.autentique.client import (
    AutentiqueDocumentSummary,
    AutentiqueSigner,
)
from classificacao_procons.contratos.autentique.webhook import AutentiqueWebhookEvent
from classificacao_procons.contratos.constants import (
    CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
    SIGNER_EMAIL_JAN,
    SIGNER_EMAIL_LUCIANO,
)
from classificacao_procons.contratos.controle_sync import (
    _resolve_controle_group_id,
    _resolve_tipo_label,
    process_document_created_webhook_event,
    register_document_in_controle,
)


class TestControleRegistration:
    @patch("classificacao_procons.contratos.controle_sync.create_controle_assinatura_item")
    @patch("classificacao_procons.contratos.controle_sync.load_controle_board_groups")
    @patch("classificacao_procons.contratos.controle_sync.fetch_document_summary")
    @patch("classificacao_procons.contratos.controle_sync.find_controle_item_by_autentique_id")
    def test_should_register_new_document_in_jan_group_with_tipo(
        self,
        find_mock,
        fetch_mock,
        load_groups_mock,
        create_item_mock,
    ) -> None:
        find_mock.return_value = None
        fetch_mock.return_value = AutentiqueDocumentSummary(
            document_id="doc-new",
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
                    signed_at=None,
                ),
            ),
        )
        load_groups_mock.return_value = {
            "assinados": "group-assinados",
            "contratos pendentes de assinatura jan": "group-jan",
            "contratos pendentes de assinatura luciano": "group-luciano",
        }
        create_item_mock.return_value = ("111", "https://monday/item/111")

        result = register_document_in_controle(
            document_id="doc-new",
            monday_api_token="monday-token",
            autentique_api_token="autentique-token",
        )

        assert result.skipped_duplicate is False
        assert result.monday_item_id == "111"
        assert result.group_id == "group-jan"
        assert result.tipo_filled is True
        assert result.status_label == CONTROLE_STATUS_AGUARDANDO_ASSINATURA
        create_item_mock.assert_called_once()
        assert create_item_mock.call_args.kwargs["group_id"] == "group-jan"
        assert create_item_mock.call_args.kwargs["tipo_label"] is not None

    @patch("classificacao_procons.contratos.controle_sync.find_controle_item_by_autentique_id")
    def test_should_skip_when_document_already_exists(self, find_mock) -> None:
        from classificacao_procons.contratos.models import ControleAssinaturasItem

        find_mock.return_value = ControleAssinaturasItem(
            item_id="999",
            name="Contrato",
            status=None,
            tipo=None,
            signature_link="Autentique ID: doc-existing",
        )

        result = register_document_in_controle(
            document_id="doc-existing",
            monday_api_token="monday-token",
        )

        assert result.skipped_duplicate is True
        assert result.monday_item_id is None

    @patch("classificacao_procons.contratos.controle_sync.register_document_in_controle")
    def test_should_process_document_created_webhook(self, register_mock) -> None:
        from classificacao_procons.contratos.controle_sync import ControleRegistrationResult

        register_mock.return_value = ControleRegistrationResult(
            document_id="doc-1",
            document_name="Contrato",
            monday_item_id="111",
            monday_item_url=None,
        )
        event = AutentiqueWebhookEvent(
            event_id="evt-1",
            event_type="document.created",
            document_id="doc-1",
            document_name="Contrato",
            signed_pdf_url=None,
        )

        result = process_document_created_webhook_event(event, monday_api_token="token")

        assert result.monday_item_id == "111"
        register_mock.assert_called_once_with(
            document_id="doc-1",
            document_name="Contrato",
            monday_api_token="token",
            autentique_api_token=None,
        )


class TestControleGroupAndTipoRules:
    def test_should_put_document_in_luciano_group_when_only_jan_signed(self) -> None:
        document = AutentiqueDocumentSummary(
            document_id="doc-1",
            name="Contrato",
            created_at=None,
            signed_pdf_url=None,
            signatures=(
                AutentiqueSigner(
                    public_id="1",
                    name="Jan",
                    email=SIGNER_EMAIL_JAN,
                    short_link=None,
                    signed_at="2026-07-16T10:00:00Z",
                ),
                AutentiqueSigner(
                    public_id="2",
                    name="Luciano",
                    email=SIGNER_EMAIL_LUCIANO,
                    short_link=None,
                    signed_at=None,
                ),
            ),
        )
        groups = {
            "assinados": "g-assinados",
            "contratos pendentes de assinatura jan": "g-jan",
            "contratos pendentes de assinatura luciano": "g-luciano",
        }

        group_id = _resolve_controle_group_id(document=document, groups=groups)

        assert group_id == "g-luciano"

    def test_should_not_fill_tipo_in_luciano_group(self) -> None:
        groups = {
            "contratos pendentes de assinatura luciano": "g-luciano",
        }

        tipo = _resolve_tipo_label(
            document_name="Contrato B2B - Empresa",
            group_id="g-luciano",
            groups=groups,
        )

        assert tipo is None

    def test_should_not_fill_tipo_for_aditivo(self) -> None:
        groups = {"contratos pendentes de assinatura jan": "g-jan"}

        tipo = _resolve_tipo_label(
            document_name="Aditivo Locação - Tower Bridge",
            group_id="g-jan",
            groups=groups,
        )

        assert tipo is None
