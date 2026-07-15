"""Parsing e validação de webhooks do Autentique."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass


class AutentiqueWebhookError(ValueError):
    """Payload de webhook inválido."""


@dataclass(frozen=True)
class AutentiqueWebhookEvent:
    event_id: str
    event_type: str
    document_id: str
    document_name: str
    signed_pdf_url: str | None


def verify_webhook_signature(
    *,
    raw_body: bytes,
    signature_header: str | None,
    secret: str,
) -> bool:
    """Valida HMAC-SHA256 do header X-Autentique-Signature."""
    if not signature_header or not secret:
        return False

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        return False

    payload_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    calculated = hmac.new(secret.encode("utf-8"), payload_json, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calculated, signature_header)


def parse_webhook_event(raw_body: bytes) -> AutentiqueWebhookEvent:
    """Extrai dados relevantes de um webhook do Autentique."""
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise AutentiqueWebhookError("Corpo do webhook não é JSON válido.") from exc

    event = payload.get("event")
    if not isinstance(event, dict):
        raise AutentiqueWebhookError("Campo event ausente no webhook.")

    event_type = str(event.get("type", "")).strip()
    if not event_type:
        raise AutentiqueWebhookError("Tipo de evento ausente no webhook.")

    event_id = str(event.get("id", "")).strip()
    data = event.get("data")
    if not isinstance(data, dict):
        raise AutentiqueWebhookError("Campo event.data ausente no webhook.")

    document_id = str(data.get("id", "")).strip()
    if not document_id:
        raise AutentiqueWebhookError("ID do documento ausente no webhook.")

    document_name = str(data.get("name", "")).strip()
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    signed_pdf_url = files.get("signed") if isinstance(files, dict) else None

    return AutentiqueWebhookEvent(
        event_id=event_id,
        event_type=event_type,
        document_id=document_id,
        document_name=document_name,
        signed_pdf_url=signed_pdf_url,
    )
