#!/usr/bin/env python3
"""Lista a árvore de pastas dentro da pasta raiz de Contratos no Google Drive."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from googleapiclient.discovery import build  # noqa: E402
from googleapiclient.errors import HttpError  # noqa: E402

from classificacao_procons.google_auth import GoogleAuthError, load_credentials  # noqa: E402

DEFAULT_CONTRATOS_FOLDER_ID = "1UiWRh2iL-ee8ozZxmkeaZSI0Lned9r1y"
DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
OUTPUT_PATH = ROOT / "artifacts" / "drive-contratos-folders.json"


def _folder_id_from_env() -> str:
    folder_id = os.environ.get("CONTRATOS_DRIVE_FOLDER_ID", DEFAULT_CONTRATOS_FOLDER_ID).strip()
    if not folder_id:
        return DEFAULT_CONTRATOS_FOLDER_ID
    return folder_id


def _list_child_folders(service, *, parent_id: str) -> list[dict[str, str]]:
    query = (
        f"'{parent_id}' in parents and "
        f"mimeType = '{DRIVE_FOLDER_MIME}' and "
        "trashed = false"
    )
    folders: list[dict[str, str]] = []
    page_token: str | None = None

    while True:
        response = (
            service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name, webViewLink)",
                pageSize=200,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                orderBy="name",
            )
            .execute()
        )
        for item in response.get("files", []):
            folders.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "url": item.get("webViewLink", ""),
                },
            )
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return folders


def _walk_folders(
    service,
    *,
    parent_id: str,
    parent_path: str,
    max_depth: int,
    current_depth: int = 0,
) -> list[dict[str, object]]:
    if current_depth > max_depth:
        return []

    nodes: list[dict[str, object]] = []
    for folder in _list_child_folders(service, parent_id=parent_id):
        path = f"{parent_path}/{folder['name']}" if parent_path else folder["name"]
        node: dict[str, object] = {
            "name": folder["name"],
            "id": folder["id"],
            "path": path,
            "url": folder["url"],
            "depth": current_depth + 1,
        }
        if current_depth < max_depth:
            node["children"] = _walk_folders(
                service,
                parent_id=folder["id"],
                parent_path=path,
                max_depth=max_depth,
                current_depth=current_depth + 1,
            )
        nodes.append(node)
    return nodes


def _print_tree(nodes: list[dict[str, object]], *, indent: int = 0) -> None:
    for node in nodes:
        prefix = "  " * indent
        print(f"{prefix}- {node['name']} ({node['id']})")
        children = node.get("children", [])
        if isinstance(children, list):
            _print_tree(children, indent=indent + 1)


def main() -> int:
    token_path = os.environ.get("GMAIL_TOKEN_PATH", "credentials/gmail-token.json")
    max_depth = int(os.environ.get("DRIVE_TREE_MAX_DEPTH", "3"))
    folder_id = _folder_id_from_env()

    try:
        credentials = load_credentials(token_path)
    except GoogleAuthError as exc:
        print(f"Erro de autenticação Google: {exc}", file=sys.stderr)
        print(
            "\nSiga o guia em docs/ativar-24h-simples.md para gerar o token "
            "(use a conta que tem acesso à pasta Contratos no Drive).",
            file=sys.stderr,
        )
        return 1

    service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    try:
        root_metadata = (
            service.files()
            .get(fileId=folder_id, fields="id, name, webViewLink", supportsAllDrives=True)
            .execute()
        )
    except HttpError as exc:
        print(
            f"Não foi possível abrir a pasta de Contratos ({folder_id}). "
            f"Verifique se a conta Google autorizada tem acesso.\n{exc}",
            file=sys.stderr,
        )
        return 1

    tree = _walk_folders(
        service,
        parent_id=folder_id,
        parent_path="",
        max_depth=max_depth,
    )

    payload = {
        "root": {
            "id": root_metadata["id"],
            "name": root_metadata.get("name", "Contratos"),
            "url": root_metadata.get("webViewLink", ""),
        },
        "max_depth": max_depth,
        "folder_count_level_1": len(tree),
        "tree": tree,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Pasta raiz: {root_metadata.get('name')} ({folder_id})")
    print(f"Subpastas de 1º nível: {len(tree)}")
    print(f"Profundidade máxima: {max_depth}")
    print("\nÁrvore de pastas:\n")
    _print_tree(tree)
    print(f"\nArquivo salvo em: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
