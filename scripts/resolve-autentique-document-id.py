#!/usr/bin/env python3
"""Resolve document ID do Autentique para testes manuais."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

AUTENTIQUE_API_URL = "https://api.autentique.com.br/v2/graphql"


def main() -> int:
    token = os.environ.get("AUTENTIQUE_API_TOKEN", "").strip()
    if not token:
        print("AUTENTIQUE_API_TOKEN não configurada.", file=sys.stderr)
        return 1

    document_id = os.environ.get("INPUT_DOCUMENT_ID", "").strip()
    if document_id:
        print(document_id)
        return 0

    query = """
    query {
      documents(limit: 20, page: 1) {
        data {
          id
          name
          files { signed }
        }
      }
    }
    """
    request = urllib.request.Request(
        AUTENTIQUE_API_URL,
        data=json.dumps({"query": query}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print(f"Autentique HTTP {exc.code}: {error_body}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Autentique indisponível: {exc.reason}", file=sys.stderr)
        return 1

    docs = body.get("data", {}).get("documents", {}).get("data", [])
    signed = [doc for doc in docs if doc.get("files", {}).get("signed")]
    if not signed:
        print("Nenhum documento assinado encontrado no Autentique.", file=sys.stderr)
        return 1

    chosen = signed[0]
    print(chosen["id"])
    print(f"Documento de teste: {chosen.get('name', '')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
