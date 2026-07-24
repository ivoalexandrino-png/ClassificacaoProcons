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
class AutentiqueSigner:
    public_id: str
    name: str | None
    email: str | None
    short_link: str | None
    signed_at: str | None


@dataclass(frozen=True)
class AutentiqueDocumentSummary:
    document_id: str
    name: str
    created_at: str | None
    signed_pdf_url: str | None
    signatures: tuple[AutentiqueSigner, ...]

    @property
    def is_fully_signed(self) -> bool:
        return is_document_fully_signed(
            signed_pdf_url=self.signed_pdf_url,
            signatures=self.signatures,
        )

    def primary_signature_link(self) -> str | None:
        for signer in self.signatures:
            if signer.short_link:
                return signer.short_link
        return None


@dataclass(frozen=True)
class AutentiqueDocument:
    document_id: str
    name: str
    signed_pdf_url: str | None
    original_pdf_url: str | None
    created_at: str | None = None


def is_document_fully_signed(
    *,
    signed_pdf_url: str | None,
    signatures: tuple[AutentiqueSigner, ...] = (),
) -> bool:
    """Indica se todas as assinaturas foram concluídas.

    O Autentique pode expor `files.signed` antes do último signatário; por isso
    validamos cada assinatura quando a lista de signatários está disponível.
    """
    if signatures:
        return all(signer.signed_at for signer in signatures)
    return bool(signed_pdf_url)


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


def _parse_signatures(raw_signatures: list[dict] | None) -> tuple[AutentiqueSigner, ...]:
    signers: list[AutentiqueSigner] = []
    for signature in raw_signatures or []:
        link = signature.get("link") or {}
        signed = signature.get("signed") or {}
        signers.append(
            AutentiqueSigner(
                public_id=str(signature.get("public_id", "")),
                name=_nullable_str(signature.get("name")),
                email=_nullable_str(signature.get("email")),
                short_link=_nullable_str(link.get("short_link")),
                signed_at=_nullable_str(signed.get("created_at")),
            ),
        )
    return tuple(signers)


def _parse_document_summary(document: dict) -> AutentiqueDocumentSummary:
    files = document.get("files") or {}
    return AutentiqueDocumentSummary(
        document_id=str(document["id"]),
        name=str(document.get("name", "")).strip(),
        created_at=document.get("created_at"),
        signed_pdf_url=files.get("signed"),
        signatures=_parse_signatures(document.get("signatures")),
    )


def _nullable_str(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def list_documents(
    *,
    api_token: str | None = None,
    page_size: int = 60,
    max_pages: int = 50,
) -> list[AutentiqueDocumentSummary]:
    """Lista documentos do Autentique com paginação."""
    token = api_token or get_api_token_from_env()
    if not token:
        raise AutentiqueClientError("AUTENTIQUE_API_TOKEN não configurada.")

    documents: list[AutentiqueDocumentSummary] = []
    for page in range(1, max_pages + 1):
        data = _graphql_request(
            api_token=token,
            query="""
            query ($limit: Int!, $page: Int!) {
              documents(limit: $limit, page: $page) {
                data {
                  id
                  name
                  created_at
                  files { signed }
                  signatures {
                    public_id
                    name
                    email
                    link { short_link }
                    signed { created_at }
                  }
                }
              }
            }
            """,
            variables={"limit": page_size, "page": page},
        )
        page_data = data.get("documents", {}).get("data", [])
        if not page_data:
            break
        documents.extend(_parse_document_summary(item) for item in page_data)
        if len(page_data) < page_size:
            break

    return documents


def fetch_document_summary(
    *,
    document_id: str,
    api_token: str | None = None,
) -> AutentiqueDocumentSummary:
    """Busca documento no Autentique com signatários (para Controle Assinaturas)."""
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
            files { signed }
            signatures {
              public_id
              name
              email
              link { short_link }
              signed { created_at }
            }
          }
        }
        """,
        variables={"documentId": document_id},
    )
    document = data.get("document")
    if not document:
        raise AutentiqueClientError(f'Documento "{document_id}" não encontrado no Autentique.')
    return _parse_document_summary(document)


def create_signature_link(
    *,
    public_id: str,
    api_token: str | None = None,
) -> str:
    """Gera link de assinatura assina.ae para um signatário."""
    token = api_token or get_api_token_from_env()
    if not token:
        raise AutentiqueClientError("AUTENTIQUE_API_TOKEN não configurada.")

    data = _graphql_request(
        api_token=token,
        query="""
        mutation ($publicId: UUID!) {
          createLinkToSignature(public_id: $publicId) {
            short_link
          }
        }
        """,
        variables={"publicId": public_id},
    )
    link = data.get("createLinkToSignature", {}).get("short_link")
    if not link:
        raise AutentiqueClientError(f"Não foi possível gerar link para assinatura {public_id}.")
    return str(link)
