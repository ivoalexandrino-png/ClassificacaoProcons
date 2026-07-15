"""Cliente GraphQL do Autentique."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

AUTENTIQUE_API_URL = "https://api.autentique.com.br/v2/graphql"
ENV_API_TOKEN = "AUTENTIQUE_API_TOKEN"


class AutentiqueClientError(RuntimeError):
    """Erro ao consultar a API do Autentique."""


@dataclass(frozen=True)
class AutentiqueDocument:
    document_id: str
    name: str
    signed_pdf_url: str | None
    original_pdf_url: str | None
    created_at: str | None = None


def get_api_token_from_env() -> str | None:
    token = os.environ.get(ENV_API_TOKEN, "").strip()
    return token or None


def _graphql_request(*, api_token: str, query: str, variables: dict | None = None) -> dict:
    payload: dict[str, object] = {"query": query}
    if variables:
        payload["variables"] = variables

    request = urllib.request.Request(
        AUTENTIQUE_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise AutentiqueClientError(f"Autentique HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise AutentiqueClientError(f"Autentique indisponível: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise AutentiqueClientError("Autentique retornou resposta inválida.") from exc

    if body.get("errors"):
        messages = "; ".join(str(item.get("message", item)) for item in body["errors"])
        raise AutentiqueClientError(messages)

    data = body.get("data")
    if not isinstance(data, dict):
        raise AutentiqueClientError("Autentique retornou payload vazio.")

    return data


def fetch_document(*, document_id: str, api_token: str | None = None) -> AutentiqueDocument:
    """Busca metadados e URLs de arquivos de um documento."""
    token = api_token or get_api_token_from_env()
    if not token:
        raise AutentiqueClientError("AUTENTIQUE_API_TOKEN não configurada.")

    data = _graphql_request(
        api_token=token,
        query="""
        query ($documentId: UUID!) {
          document(id: $documentId) {
            id
            name
            created_at
            files {
              original
              signed
            }
          }
        }
        """,
        variables={"documentId": document_id},
    )

    document = data.get("document")
    if not document:
        raise AutentiqueClientError(f'Documento "{document_id}" não encontrado no Autentique.')

    files = document.get("files") or {}
    return AutentiqueDocument(
        document_id=str(document["id"]),
        name=str(document.get("name", "")).strip(),
        signed_pdf_url=files.get("signed"),
        original_pdf_url=files.get("original"),
        created_at=document.get("created_at"),
    )


def download_file(*, url: str, destination: Path) -> Path:
    """Baixa PDF do Autentique para disco local."""
    if not url:
        raise AutentiqueClientError("URL de download vazia.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            destination.write_bytes(response.read())
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise AutentiqueClientError(f"Falha ao baixar PDF ({exc.code}): {error_body}") from exc
    except urllib.error.URLError as exc:
        raise AutentiqueClientError(f"Falha ao baixar PDF: {exc.reason}") from exc

    if not destination.exists() or destination.stat().st_size == 0:
        raise AutentiqueClientError("PDF baixado está vazio.")

    return destination
