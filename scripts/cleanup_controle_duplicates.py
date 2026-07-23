"""Remove duplicatas seguras no Controle Assinaturas (mesmo ID Autentique)."""

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

from classificacao_procons.contratos.autentique.client import (
    AutentiqueClientError,
    fetch_document_summary,
)
from classificacao_procons.contratos.constants import (
    CONTROLE_COL_LINK_ASSINADO,
    CONTROLE_COL_LINK_ASSINATURA,
    CONTROLE_COL_STATUS,
    CONTROLE_COL_TIPO,
    CONTROLE_STATUS_ASSINADO,
    MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
)
from classificacao_procons.contratos.monday_contracts import _extract_document_ids_from_text
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
    return ids


@dataclass
class ControleSnapshot:
    item_id: str
    name: str
    group_title: str
    status: str | None
    tipo: str | None
    signature_link: str | None
    signed_link: str | None
    autentique_ids: set[str] = field(default_factory=set)
    drive_ids: set[str] = field(default_factory=set)

    @property
    def is_aprovar_name(self) -> bool:
        return normalize_name(self.name).startswith("aprovar ")

    @property
    def completeness(self) -> int:
        score = 0
        if self.status == CONTROLE_STATUS_ASSINADO:
            score += 20
        elif self.status and "aguardando" in self.status.casefold():
            score += 5
        if self.tipo:
            score += 3
        if self.signed_link:
            score += 15
        if self.signature_link:
            score += 5
        if self.drive_ids:
            score += 10
        if not self.is_aprovar_name:
            score += 5
        return score


def fetch_controle_items(api_token: str) -> list[ControleSnapshot]:
    items: list[ControleSnapshot] = []
    cursor: str | None = None
    column_ids = [
        CONTROLE_COL_STATUS,
        CONTROLE_COL_TIPO,
        CONTROLE_COL_LINK_ASSINATURA,
        CONTROLE_COL_LINK_ASSINADO,
    ]
    for _ in range(80):
        data = _graphql_request(
            api_token=api_token,
            query="""
            query ($boardId: ID!, $limit: Int!, $cursor: String, $columnIds: [String!]) {
              boards(ids: [$boardId]) {
                items_page(limit: $limit, cursor: $cursor) {
                  cursor
                  items {
                    id
                    name
                    group { title }
                    column_values(ids: $columnIds) {
                      id
                      text
                      value
                    }
                  }
                }
              }
            }
            """,
            variables={
                "boardId": MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
                "limit": 100,
                "cursor": cursor,
                "columnIds": column_ids,
            },
        )
        page = data["boards"][0]["items_page"]
        for raw in page["items"]:
            values = {col["id"]: col for col in raw.get("column_values", [])}
            signature = str(values.get(CONTROLE_COL_LINK_ASSINATURA, {}).get("text") or "")
            signed = str(values.get(CONTROLE_COL_LINK_ASSINADO, {}).get("text") or "")
            autentique_ids: set[str] = set()
            for col in values.values():
                text = f"{col.get('text') or ''}\n{col.get('value') or ''}"
                autentique_ids.update(_extract_document_ids_from_text(text))
            drive_ids = extract_drive_ids(signature, signed)
            items.append(
                ControleSnapshot(
                    item_id=str(raw["id"]),
                    name=str(raw.get("name", "")),
                    group_title=str((raw.get("group") or {}).get("title") or ""),
                    status=values.get(CONTROLE_COL_STATUS, {}).get("text"),
                    tipo=values.get(CONTROLE_COL_TIPO, {}).get("text"),
                    signature_link=signature or None,
                    signed_link=signed or None,
                    autentique_ids=autentique_ids,
                    drive_ids=drive_ids,
                )
            )
        cursor = page.get("cursor")
        if not cursor:
            break
    return items


def choose_keeper(members: list[ControleSnapshot]) -> ControleSnapshot:
    return max(
        members,
        key=lambda item: (
            item.completeness,
            len(item.drive_ids),
            1 if item.tipo == "RH" else 0,
            -int(item.item_id),
        ),
    )


def is_safe_duplicate(*, keeper: ControleSnapshot, candidate: ControleSnapshot) -> tuple[bool, str]:
    if candidate.item_id == keeper.item_id:
        return False, "É o item mantido"

    if not keeper.autentique_ids & candidate.autentique_ids:
        return False, "IDs Autentique não coincidem"

    if candidate.drive_ids and keeper.drive_ids and not (candidate.drive_ids & keeper.drive_ids):
        return False, "PDF assinado diferente no Monday — revisar manualmente"

    if keeper.signed_link and not candidate.signed_link:
        return True, "Item mantido tem link assinado; duplicata sem PDF"

    if candidate.is_aprovar_name and not keeper.is_aprovar_name:
        return True, "Par Aprovar/documento final — remover item Aprovar"

    if keeper.is_aprovar_name and not candidate.is_aprovar_name:
        return True, "Par Aprovar/documento final — remover item Aprovar"

    if int(candidate.item_id) > int(keeper.item_id):
        return True, "Mesmo ID Autentique — manter item mais completo/antigo"

    return False, "Item candidato é mais antigo/completo que o mantido"


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


def verify_autentique_document(document_id: str) -> tuple[bool, str]:
    try:
        summary = fetch_document_summary(document_id=document_id)
    except AutentiqueClientError as exc:
        message = str(exc)
        if "não configurada" in message.casefold():
            return True, "Autentique não configurado — validação somente via Monday"
        return False, message
    status = "assinado" if summary.is_fully_signed else "pendente"
    return True, f"{summary.name} ({status})"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Limpa duplicatas no Controle Assinaturas (mesmo ID Autentique)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--report",
        default="artifacts/controle-cleanup-executed.csv",
    )
    args = parser.parse_args()

    monday_token = get_api_token_from_env()
    if not monday_token:
        print("MONDAY_API_TOKEN não configurada.", file=sys.stderr)
        return 1

    print("Carregando itens do Controle Assinaturas...")
    items = fetch_controle_items(monday_token)
    by_autentique: dict[str, list[ControleSnapshot]] = defaultdict(list)
    for item in items:
        for doc_id in item.autentique_ids:
            by_autentique[doc_id].append(item)

    duplicate_groups: dict[str, list[ControleSnapshot]] = {}
    for doc_id, group in by_autentique.items():
        unique = {item.item_id: item for item in group}
        if len(unique) >= 2:
            duplicate_groups[doc_id] = list(unique.values())

    print(
        f"Total itens: {len(items)} | Grupos com mesmo ID Autentique: {len(duplicate_groups)}"
    )

    to_archive: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    autentique_cache: dict[str, tuple[bool, str]] = {}

    for doc_id, group in sorted(duplicate_groups.items()):
        if doc_id not in autentique_cache:
            autentique_cache[doc_id] = verify_autentique_document(doc_id)
            time.sleep(0.1)
        aut_ok, aut_detail = autentique_cache[doc_id]

        keeper = choose_keeper(group)
        for candidate in group:
            if candidate.item_id == keeper.item_id:
                continue
            safe, reason = is_safe_duplicate(keeper=keeper, candidate=candidate)
            if not aut_ok:
                safe = False
                reason = f"Autentique indisponível: {aut_detail}"

            row = {
                "autentique_id": doc_id,
                "autentique_detail": aut_detail,
                "keeper_id": keeper.item_id,
                "keeper_name": keeper.name,
                "keeper_status": keeper.status or "",
                "keeper_tipo": keeper.tipo or "",
                "item_id": candidate.item_id,
                "item_name": candidate.name,
                "item_status": candidate.status or "",
                "item_tipo": candidate.tipo or "",
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
        "autentique_id",
        "autentique_detail",
        "keeper_id",
        "keeper_name",
        "keeper_status",
        "keeper_tipo",
        "item_id",
        "item_name",
        "item_status",
        "item_tipo",
        "action",
        "reason",
        "executed",
        "error",
    ]

    print(f"Arquivar com segurança: {len(to_archive)} | Ignorados: {len(skipped)}")

    # Um item pode aparecer em mais de um grupo (IDs Autentique compartilhados).
    deduped_archive: list[dict[str, str]] = []
    seen_item_ids: set[str] = set()
    for row in to_archive:
        if row["item_id"] in seen_item_ids:
            continue
        seen_item_ids.add(row["item_id"])
        deduped_archive.append(row)
    if len(deduped_archive) != len(to_archive):
        print(f"Deduplicados: {len(to_archive)} -> {len(deduped_archive)} itens únicos")

    executed = 0
    errors = 0
    with report_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        archived_ids = {row["item_id"] for row in deduped_archive}
        for row in deduped_archive + skipped:
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
