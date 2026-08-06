"""Testes de registro de webhooks Autentique."""

from unittest.mock import patch

from classificacao_procons.contratos.autentique.webhook_endpoints import (
    WEBHOOK_NAME_DOCUMENT,
    ensure_contratos_autentique_webhooks,
)


class TestEnsureContratosAutentiqueWebhooks:
    @patch("classificacao_procons.contratos.autentique.webhook_endpoints._create_endpoint")
    @patch("classificacao_procons.contratos.autentique.webhook_endpoints._list_endpoints")
    @patch("classificacao_procons.contratos.autentique.webhook_endpoints._resolve_organization_id")
    def test_should_create_document_and_signature_endpoints_when_missing(
        self,
        resolve_org_mock,
        list_mock,
        create_mock,
    ) -> None:
        resolve_org_mock.return_value = 99
        list_mock.return_value = []
        create_mock.side_effect = [
            type(
                "Info",
                (),
                {
                    "endpoint_id": "d1",
                    "url": "https://svc/webhooks/autentique",
                    "name": WEBHOOK_NAME_DOCUMENT,
                    "secret": "sec-doc",
                    "created": True,
                },
            )(),
            type(
                "Info",
                (),
                {
                    "endpoint_id": "s1",
                    "url": "https://svc/webhooks/autentique",
                    "name": "B4A Contratos (assinaturas)",
                    "secret": None,
                    "created": True,
                },
            )(),
        ]

        result = ensure_contratos_autentique_webhooks(
            base_service_url="https://svc",
            api_token="token",
            organization_id=99,
        )

        assert result.webhook_url == "https://svc/webhooks/autentique"
        assert result.webhook_secret == "sec-doc"
        assert create_mock.call_count == 2
        sig_call = create_mock.call_args_list[1]
        assert sig_call.kwargs["events"] == ["SIGNATURE_ACCEPTED", "SIGNATURE_REJECTED"]

    @patch("classificacao_procons.contratos.autentique.webhook_endpoints._create_endpoint")
    @patch("classificacao_procons.contratos.autentique.webhook_endpoints._list_endpoints")
    @patch("classificacao_procons.contratos.autentique.webhook_endpoints._resolve_organization_id")
    def test_should_not_recreate_when_endpoints_already_exist(
        self,
        resolve_org_mock,
        list_mock,
        create_mock,
    ) -> None:
        resolve_org_mock.return_value = 1
        list_mock.return_value = [
            {
                "id": "existing-doc",
                "url": "https://svc/webhooks/autentique",
                "name": WEBHOOK_NAME_DOCUMENT,
            },
            {
                "id": "existing-sig",
                "url": "https://svc/webhooks/autentique",
                "name": "B4A Contratos (assinaturas)",
            },
        ]

        result = ensure_contratos_autentique_webhooks(
            base_service_url="https://svc",
            api_token="token",
            organization_id=1,
        )

        create_mock.assert_not_called()
        assert result.webhook_secret is None
        assert result.document_endpoint is not None
        assert result.document_endpoint.created is False
