"""Registro idempotente de endpoints de webhook no Autentique (API GraphQL)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from classificacao_procons.contratos.autentique.client import (
    AutentiqueClientError,
    _graphql_request,
    get_api_token_from_env,
)

ENV_ORGANIZATION_ID = "AUTENTIQUE_ORGANIZATION_ID"
WEBHOOK_NAME_DOCUMENT = "B4A Contratos (documentos)"
WEBHOOK_NAME_SIGNATURE = "B4A Contratos (assinaturas)"
SIGNATURE_WEBHOOK_EVENTS = ("SIGNATURE_ACCEPTED", "SIGNATURE_REJECTED")


@dataclass(frozen=True)
class AutentiqueWebhookEndpointInfo:
    endpoint_id: str
    url: str
    name: str
    secret: str | None
    created: bool


@dataclass(frozen=True)
class AutentiqueWebhookRegistrationResult:
    webhook_url: str
    organization_id: int
    document_endpoint: AutentiqueWebhookEndpointInfo | None
    signature_endpoint: AutentiqueWebhookEndpointInfo | None
    webhook_secret: str | None
    signature_missing_rejected_event: bool = False


def _resolve_organization_id(*, api_token: str, organization_id: int | None) -> int:
    if organization_id is not None:
        return organization_id
    env_value = os.environ.get(ENV_ORGANIZATION_ID, "").strip()
    if env_value:
        return int(env_value)
    data = _graphql_request(api_token=api_token, query="query { organization { id } }")
    org = data.get("organization")
    if not isinstance(org, dict) or org.get("id") is None:
        raise AutentiqueClientError("Não foi possível obter organization.id do Autentique.")
    return int(org["id"])


def _list_endpoints(*, api_token: str, organization_id: int) -> list[dict]:
    query = """
    query ($organizationId: Int!) {
      organization(id: $organizationId) {
        webhook_endpoints {
          id
          url
          name
          active
          events
        }
      }
    }
    """
    try:
        data = _graphql_request(
            api_token=api_token,
            query=query,
            variables={"organizationId": organization_id},
        )
    except AutentiqueClientError:
        return []
    org = data.get("organization")
    if not isinstance(org, dict):
        return []
    endpoints = org.get("webhook_endpoints")
    if not isinstance(endpoints, list):
        return []
    return [item for item in endpoints if isinstance(item, dict)]


def _create_endpoint(
    *,
    api_token: str,
    organization_id: int,
    url: str,
    name: str,
    endpoint_type: str,
    events: list[str],
) -> AutentiqueWebhookEndpointInfo:
    mutation = """
    mutation (
      $organizationId: Int!,
      $url: String!,
      $name: String!,
      $type: WebhookEndpointTypeEnum!,
      $events: [WebhookEventTypeEnum!]!
    ) {
      createEndpoint(
        organization_id: $organizationId,
        url: $url,
        format: JSON,
        type: $type,
        name: $name,
        events: $events
      ) {
        secret
        webhook_endpoint {
          id
          url
          active
        }
      }
    }
    """
    data = _graphql_request(
        api_token=api_token,
        query=mutation,
        variables={
            "organizationId": organization_id,
            "url": url,
            "name": name,
            "type": endpoint_type,
            "events": events,
        },
    )
    payload = data.get("createEndpoint")
    if not isinstance(payload, dict):
        raise AutentiqueClientError("createEndpoint retornou vazio.")
    endpoint = payload.get("webhook_endpoint")
    if not isinstance(endpoint, dict):
        raise AutentiqueClientError("createEndpoint sem webhook_endpoint.")
    secret = payload.get("secret")
    return AutentiqueWebhookEndpointInfo(
        endpoint_id=str(endpoint.get("id", "")),
        url=str(endpoint.get("url", url)),
        name=name,
        secret=str(secret) if secret else None,
        created=True,
    )


def _find_existing(
    endpoints: list[dict],
    *,
    url: str,
    name: str,
) -> dict | None:
    target_url = url.rstrip("/")
    for item in endpoints:
        item_url = str(item.get("url", "")).rstrip("/")
        item_name = str(item.get("name", ""))
        if item_url == target_url and item_name == name:
            return item
    return None


def _signature_endpoint_needs_rejected_event(endpoint: dict) -> bool:
    raw_events = endpoint.get("events")
    if not isinstance(raw_events, list):
        return True
    normalized = {str(item).upper() for item in raw_events}
    return "SIGNATURE_REJECTED" not in normalized


def ensure_contratos_autentique_webhooks(
    *,
    base_service_url: str,
    api_token: str | None = None,
    organization_id: int | None = None,
) -> AutentiqueWebhookRegistrationResult:
    """Garante endpoints DOCUMENT + SIGNATURE apontando para /webhooks/autentique."""
    token = api_token or get_api_token_from_env()
    if not token:
        raise AutentiqueClientError("AUTENTIQUE_API_TOKEN não configurada.")

    base = base_service_url.rstrip("/")
    webhook_url = f"{base}/webhooks/autentique"
    org_id = _resolve_organization_id(api_token=token, organization_id=organization_id)
    existing = _list_endpoints(api_token=token, organization_id=org_id)

    document_info: AutentiqueWebhookEndpointInfo | None = None
    signature_info: AutentiqueWebhookEndpointInfo | None = None
    secrets: list[str] = []

    signature_missing_rejected = False

    doc_existing = _find_existing(existing, url=webhook_url, name=WEBHOOK_NAME_DOCUMENT)
    if doc_existing:
        document_info = AutentiqueWebhookEndpointInfo(
            endpoint_id=str(doc_existing.get("id", "")),
            url=webhook_url,
            name=WEBHOOK_NAME_DOCUMENT,
            secret=None,
            created=False,
        )
    else:
        document_info = _create_endpoint(
            api_token=token,
            organization_id=org_id,
            url=webhook_url,
            name=WEBHOOK_NAME_DOCUMENT,
            endpoint_type="DOCUMENT",
            events=["DOCUMENT_CREATED", "DOCUMENT_FINISHED"],
        )
        if document_info.secret:
            secrets.append(document_info.secret)

    sig_existing = _find_existing(existing, url=webhook_url, name=WEBHOOK_NAME_SIGNATURE)
    if sig_existing:
        signature_info = AutentiqueWebhookEndpointInfo(
            endpoint_id=str(sig_existing.get("id", "")),
            url=webhook_url,
            name=WEBHOOK_NAME_SIGNATURE,
            secret=None,
            created=False,
        )
        signature_missing_rejected = _signature_endpoint_needs_rejected_event(sig_existing)
    else:
        signature_info = _create_endpoint(
            api_token=token,
            organization_id=org_id,
            url=webhook_url,
            name=WEBHOOK_NAME_SIGNATURE,
            endpoint_type="SIGNATURE",
            events=list(SIGNATURE_WEBHOOK_EVENTS),
        )
        if signature_info.secret:
            secrets.append(signature_info.secret)

    webhook_secret = secrets[0] if secrets else None
    return AutentiqueWebhookRegistrationResult(
        webhook_url=webhook_url,
        organization_id=org_id,
        document_endpoint=document_info,
        signature_endpoint=signature_info,
        webhook_secret=webhook_secret,
        signature_missing_rejected_event=signature_missing_rejected,
    )
