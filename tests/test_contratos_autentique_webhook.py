"""Testes de webhook do Autentique."""

import hashlib
import hmac
import json

from classificacao_procons.contratos.autentique.webhook import (
    AutentiqueWebhookError,
    parse_webhook_event,
    verify_webhook_signature,
)


def _sample_payload() -> dict[str, object]:
    return {
        "event": {
            "id": "evt-1",
            "type": "document.finished",
            "data": {
                "id": "doc-123",
                "name": "Contrato B2B Teste",
                "files": {"signed": "https://example.com/signed.pdf"},
            },
        },
    }


class TestAutentiqueWebhook:
    def test_should_parse_document_finished_event(self) -> None:
        raw = json.dumps(_sample_payload()).encode("utf-8")
        event = parse_webhook_event(raw)
        assert event.event_type == "document.finished"
        assert event.document_id == "doc-123"
        assert event.document_name == "Contrato B2B Teste"
        assert event.signed_pdf_url == "https://example.com/signed.pdf"

    def test_should_reject_invalid_payload(self) -> None:
        try:
            parse_webhook_event(b"{}")
        except AutentiqueWebhookError:
            return
        raise AssertionError("expected AutentiqueWebhookError")

    def test_should_verify_signature(self) -> None:
        payload = _sample_payload()
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        secret = "test-secret"
        signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        assert verify_webhook_signature(
            raw_body=json.dumps(payload).encode("utf-8"),
            signature_header=signature,
            secret=secret,
        )
