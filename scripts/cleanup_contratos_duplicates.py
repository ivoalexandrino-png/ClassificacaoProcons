"""Remove duplicatas seguras no quadro Contratos (Monday + Drive)."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from classificacao_procons.contratos.constants import MONDAY_CONTRATOS_BOARD_ID
from classificacao_procons.contratos.drive_routing import build_contract_pdf_filename
from classificacao_procons.drive.client import DriveClientError, _build_drive_service
from classificacao_procons.monday.client import MondayClientError, _graphql_request, get_api_token_from_env

DRIVE_ID_RE = re.compile(r"(?:/d/|id=)([a-zA-Z0-9_-]{10,})")


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_marks).strip()


def extract_drive_ids(*parts: str | None) -> set[str]:
    ids: set[str] = set()
    for part in parts:
        if not part:
            continue
        for match in DRIVE_ID_RE.findall(part):
            ids.add(match)
        try:
            payload = json.loads(part)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            for key in ("fileId", "file_id", "id"):
                raw = payload.get(key)
                if isinstance(raw, str) and raw:
                    ids.add(raw)
            assets = payload.get("files") or payload.get("assets")
            if isinstance(assets, list):
                for asset in assets:
                    if isinstance(asset, dict):
                        asset_id = asset.get("fileId") or asset.get("id") or asset.get("assetId")
                        if asset_id:
                            ids.add(str(asset_id))
    return ids


@dataclass
class ItemSnapshot:
    item_id: str
    name: str
    group_title: str
    column_text: dict[str, str] = field(default_factory=dict)
    drive_ids: set[str] = field(default_factory=set)
    link_urls: list[str] = field(default_factory=list)
    filled_columns: int = 0
    drive_verified: dict[str, str] = field(default_factory=dict)

    @property
    def completeness(self) -> int:
        score = self.filled_columns
        if self.drive_ids:
            score += 10
        if self.drive_verified:
            score += 5
        return score


def fetch_contratos_items(api_token: str) -> list[ItemSnapshot]:
    items: list[ItemSnapshot] = []
    cursor: str | None = None
    for _ in range(80):
        data = _graphql_request(
            api_token=api_token,
            query="""
            query ($boardId: ID!, $limit: Int!, $cursor: String) {
              boards(ids: [$boardId]) {
                items_page(limit: $limit, cursor: $cursor) {
                  cursor
                  items {
                    id
                    name
                    group { title }
                    column_values {
                      id
                      text
                      value
                      type
                    }
                  }
                }
              }
            }
            """,
            variables={"boardId": MONDAY_CONTRATOS_BOARD_ID, "limit": 100, "cursor": cursor},
        )
        page = data["boards"][0]["items_page"]
        for raw in page["items"]:
            column_text: dict[str, str] = {}
            drive_ids: set[str] = set()
            link_urls: list[str] = []
            filled = 0
            for column in raw.get("column_values", []):
                text = str(column.get("text") or "").strip()
                value = str(column.get("value") or "").strip()
                col_type = str(column.get("type") or "")
                col_id = str(column.get("id") or "")
                if text:
                    column_text[col_id] = text
                    filled += 1
                ids = extract_drive_ids(text, value)
                drive_ids.update(ids)
                if col_type == "link" and value:
                    try:
                        payload = json.loads(value)
                        url = str(payload.get("url") or "")
                        if url:
                            link_urls.append(url)
                            drive_ids.update(extract_drive_ids(url))
                    except json.JSONDecodeError:
                        pass
            items.append(
                ItemSnapshot(
                    item_id=str(raw["id"]),
                    name=str(raw.get("name", "")),
                    group_title=str((raw.get("group") or {}).get("title") or ""),
                    column_text=column_text,
                    drive_ids=drive_ids,
                    link_urls=link_urls,
                    filled_columns=filled,
                )
            )
        cursor = page.get("cursor")
        if not cursor:
            break
    return items


def verify_drive_files(
    service,
    drive_ids: set[str],
    *,
    cache: dict[str, str | None],
) -> dict[str, str]:
    verified: dict[str, str] = {}
    for file_id in drive_ids:
        if file_id in cache:
            name = cache[file_id]
        else:
            try:
                metadata = (
                    service.files()
                    .get(fileId=file_id, fields="id,name,trashed", supportsAllDrives=True)
                    .execute()
                )
                if metadata.get("trashed"):
                    name = None
                else:
                    name = str(metadata.get("name") or "")
            except Exception:
                name = None
            cache[file_id] = name
            time.sleep(0.05)
        if name:
            verified[file_id] = name
    return verified


def choose_keeper(members: list[ItemSnapshot]) -> ItemSnapshot:
    return max(
        members,
        key=lambda item: (
            item.completeness,
            len(item.drive_verified),
            len(item.drive_ids),
            item.filled_columns,
            -int(item.item_id),
        ),
    )


def is_safe_duplicate(*, keeper: ItemSnapshot, candidate: ItemSnapshot) -> tuple[bool, str]:
    if candidate.item_id == keeper.item_id:
        return False, "É o item mantido"

    if not candidate.drive_ids and not keeper.drive_ids:
        if int(candidate.item_id) > int(keeper.item_id):
            return True, "Sem PDF em ambos — duplicata vazia de catch-up (ID mais novo)"
        return False, "Sem PDF — manter o mais antigo/enriquecido"

    if candidate.drive_ids and keeper.drive_ids:
        if candidate.drive_ids <= keeper.drive_ids:
            return True, "Mesmo(s) arquivo(s) Drive do item mantido"
        if keeper.drive_ids & candidate.drive_ids:
            return True, "Compartilha arquivo Drive com o item mantido"
        return False, "PDF Drive diferente — pode ser contrato distinto"

    if keeper.drive_ids and not candidate.drive_ids:
        return True, "Item mantido tem PDF; duplicata sem anexo"

    if candidate.drive_ids and not keeper.drive_ids:
        return False, "Duplicata tem PDF e o mantido não — não apagar"

    return False, "Não atende critérios de segurança"


def archive_monday_item(api_token: str, item_id: str) -> None:
    _graphql_request(
        api_token=api_token,
        query="""
        mutation ($itemId: ID!) {
          archive_item(item_id: $itemId) { id }
        }
        """,
        variables={"itemId": item_id},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Limpa duplicatas seguras no quadro Contratos")
    parser.add_argument("--dry-run", action="store_true", help="Somente simular")
    parser.add_argument(
        "--token-path",
        default="credentials/gmail-token.json",
        help="Token Google Drive",
    )
    parser.add_argument(
        "--report",
        default="artifacts/contratos-cleanup-executed.csv",
        help="CSV com resultado da execução",
    )
    args = parser.parse_args()

    monday_token = get_api_token_from_env()
    if not monday_token:
        print("MONDAY_API_TOKEN não configurada.", file=sys.stderr)
        return 1

    print("Carregando itens do quadro Contratos...")
    items = fetch_contratos_items(monday_token)
    by_name: dict[str, list[ItemSnapshot]] = defaultdict(list)
    for item in items:
        key = normalize_name(item.name)
        if key:
            by_name[key].append(item)

    duplicate_groups = {key: group for key, group in by_name.items() if len(group) > 1}
    print(f"Total itens: {len(items)} | Grupos duplicados: {len(duplicate_groups)}")

    try:
        drive_service = _build_drive_service(args.token_path)
    except DriveClientError as exc:
        print(f"Drive indisponível: {exc}", file=sys.stderr)
        return 1

    drive_cache: dict[str, str | None] = {}
    for group in duplicate_groups.values():
        for item in group:
            item.drive_verified = verify_drive_files(drive_service, item.drive_ids, cache=drive_cache)

    to_archive: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    for key, group in sorted(duplicate_groups.items()):
        keeper = choose_keeper(group)
        expected_pdf = build_contract_pdf_filename(document_name=keeper.name).casefold()
        for candidate in group:
            if candidate.item_id == keeper.item_id:
                continue
            safe, reason = is_safe_duplicate(keeper=keeper, candidate=candidate)
            if safe and candidate.drive_verified:
                names = {name.casefold() for name in candidate.drive_verified.values()}
                if expected_pdf not in names and len(candidate.drive_verified) == 1:
                    only_name = next(iter(candidate.drive_verified.values())).casefold()
                    if normalize_name(only_name) != normalize_name(keeper.name):
                        safe = False
                        reason = (
                            "Nome do PDF no Drive difere do item — revisar manualmente"
                        )
            row = {
                "group_key": key[:120],
                "keeper_id": keeper.item_id,
                "keeper_name": keeper.name,
                "keeper_drive_ids": ",".join(sorted(keeper.drive_ids)),
                "item_id": candidate.item_id,
                "item_name": candidate.name,
                "item_drive_ids": ",".join(sorted(candidate.drive_ids)),
                "action": "ARCHIVE" if safe else "SKIP",
                "reason": reason,
            }
            if safe:
                to_archive.append(row)
            else:
                skipped.append(row)

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "group_key",
        "keeper_id",
        "keeper_name",
        "keeper_drive_ids",
        "item_id",
        "item_name",
        "item_drive_ids",
        "action",
        "reason",
        "executed",
        "error",
    ]

    print(f"Arquivar com segurança: {len(to_archive)} | Ignorados: {len(skipped)}")

    executed = 0
    errors = 0
    with report_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in to_archive + skipped:
            row = {**row, "executed": "", "error": ""}
            if row["action"] == "ARCHIVE":
                if args.dry_run:
                    row["executed"] = "dry-run"
                else:
                    try:
                        archive_monday_item(monday_token, row["item_id"])
                        row["executed"] = "yes"
                        executed += 1
                        time.sleep(0.15)
                    except MondayClientError as exc:
                        row["executed"] = "no"
                        row["error"] = str(exc)
                        errors += 1
            writer.writerow(row)

    print(f"Relatório: {report_path}")
    if args.dry_run:
        print("Dry-run — nenhum item arquivado.")
    else:
        print(f"Arquivados: {executed} | Erros: {errors}")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
