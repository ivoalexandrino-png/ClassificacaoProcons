"""Escritor APPLY da migração Monday → Sunday (Fase 3).

Somente operações CREATE com verificação por item. Não conhece domínios além do
contrato genérico: inventário Monday, BoardPlan, snapshot Sunday e SundayClient.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from classificacao_procons.migration.executor import (
    DEFAULT_LEDGER_PATH,
    ExecutionPlan,
    PlannedOperation,
    comment_idempotency_marker,
    load_persistent_ledger,
)
from classificacao_procons.migration.mappings import (
    find_main_status_column,
    item_is_concluded,
    slugify_status_key,
)
from classificacao_procons.migration.models import (
    BoardPlan,
    MondayBoardInventory,
    MondayColumnInfo,
    SundayBoardSnapshot,
)
from classificacao_procons.monday.client import _graphql_request

_ITEM_UPDATES_QUERY = """
query ($ids: [ID!], $limit: Int!) {
  items(ids: $ids) {
    id
    updates(limit: $limit) {
      id
      text_body
      created_at
      creator { name }
    }
  }
}
"""

_APPLY_ITEMS_QUERY = """
query ($ids: [ID!], $cursor: String, $limit: Int!) {
  boards(ids: $ids) {
    items_page(limit: $limit, cursor: $cursor) {
      cursor
      items {
        id
        name
        group { id }
        column_values { id type text value }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class MondayApplySource:
    item_id: str
    name: str
    group_id: str | None
    values_by_column_id: dict[str, str | None]  # text ou label de status


@dataclass(frozen=True)
class MondayUpdateSource:
    """Update do Monday a migrar como comment (conteúdo nunca vai para logs)."""

    update_id: str
    body: str
    creator_name: str | None = None
    created_at: str | None = None


@dataclass
class ApplyWriteStats:
    items_created: int = 0
    system_fields: int = 0
    custom_values: int = 0
    status_writes: int = 0
    comments: int = 0
    attachments: int = 0
    relations: int = 0
    subitems: int = 0


@dataclass
class FieldCheckReport:
    total: int = 0
    ok: int = 0
    errors: list[str] = field(default_factory=list)


def format_monday_id_column_value(monday_board_id: str, monday_item_id: str) -> str:
    """Valor único da coluna Monday ID (`board_id/item_id`)."""
    return f"{monday_board_id}/{monday_item_id}"


def parse_monday_item_id_from_column_value(raw: object) -> str | None:
    """Extrai monday_item_id de um valor da coluna Monday ID."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if "/" in text:
        return text.rsplit("/", 1)[-1].strip() or None
    if ":" in text:
        return text.rsplit(":", 1)[-1].strip() or None
    return text


def fetch_monday_apply_sources(
    api_token: str,
    board_id: str,
    *,
    item_ids: set[str] | None = None,
) -> dict[str, MondayApplySource]:
    """Lê nome + valores de coluna do Monday (somente GET GraphQL)."""
    sources: dict[str, MondayApplySource] = {}
    cursor: str | None = None
    while True:
        page = _graphql_request(
            api_token=api_token,
            query=_APPLY_ITEMS_QUERY,
            variables={"ids": [board_id], "cursor": cursor, "limit": 250},
        )["boards"][0]["items_page"]
        for item in page.get("items", []):
            item_id = str(item["id"])
            if item_ids is not None and item_id not in item_ids:
                continue
            values: dict[str, str | None] = {}
            for column_value in item.get("column_values", []):
                column_id = str(column_value.get("id", ""))
                text = (column_value.get("text") or "").strip()
                values[column_id] = text or None
            sources[item_id] = MondayApplySource(
                item_id=item_id,
                name=str(item.get("name") or "").strip(),
                group_id=(item.get("group") or {}).get("id"),
                values_by_column_id=values,
            )
        cursor = page.get("cursor")
        if not cursor:
            break
    return sources


def fetch_monday_item_updates(
    api_token: str,
    item_ids: list[str],
    *,
    limit: int = 100,
) -> dict[str, tuple[MondayUpdateSource, ...]]:
    """Lê os updates dos itens no Monday (somente GET GraphQL), mais antigos primeiro."""
    if not item_ids:
        return {}
    data = _graphql_request(
        api_token=api_token,
        query=_ITEM_UPDATES_QUERY,
        variables={"ids": item_ids, "limit": limit},
    )
    result: dict[str, tuple[MondayUpdateSource, ...]] = {}
    for item in data.get("items") or []:
        updates = [
            MondayUpdateSource(
                update_id=str(update["id"]),
                body=str(update.get("text_body") or "").strip(),
                creator_name=(update.get("creator") or {}).get("name"),
                created_at=update.get("created_at"),
            )
            for update in item.get("updates") or []
            if update.get("id") is not None
        ]
        updates.sort(key=lambda update: (update.created_at or "", update.update_id))
        result[str(item["id"])] = tuple(updates)
    return result


def build_migration_comment_body(monday_item_id: str, update: MondayUpdateSource) -> str:
    """Corpo do comment migrado: cabeçalho com autor/data + texto + marcador determinístico."""
    header_parts = ["Monday"]
    if update.creator_name:
        header_parts.append(str(update.creator_name))
    if update.created_at:
        header_parts.append(str(update.created_at))
    header = "[" + " · ".join(header_parts) + "]"
    marker = comment_idempotency_marker(monday_item_id, update.update_id)
    return f"{header}\n{update.body}\n\n{marker}"


def apply_create_comments(
    *,
    client,
    sunday_item_id: str,
    monday_item_id: str,
    updates: tuple[MondayUpdateSource, ...],
    stats: ApplyWriteStats | None = None,
) -> int:
    """Cria comments dos updates Monday, idempotente pelo marcador no corpo."""
    if not updates:
        return 0
    existing_bodies = [
        comment.body or "" for comment in client.list_comments(sunday_item_id)
    ]
    created = 0
    for update in updates:
        marker = comment_idempotency_marker(monday_item_id, update.update_id)
        if any(marker in body for body in existing_bodies):
            continue
        client.add_comment(
            sunday_item_id,
            build_migration_comment_body(monday_item_id, update),
        )
        created += 1
        if stats is not None:
            stats.comments += 1
    return created


def build_sunday_monday_id_index(
    client,
    *,
    board_id: str,
    monday_id_column_id: str,
) -> dict[str, str]:
    """Índice monday_item_id → sunday_item_id a partir da coluna Monday ID."""
    index: dict[str, str] = {}
    for item in client.list_items(board_id).items:
        raw = client.get_value(item.id, monday_id_column_id)
        monday_item_id = parse_monday_item_id_from_column_value(raw)
        if monday_item_id:
            index[monday_item_id] = item.id
    return index


def derive_system_status_key(inventory: MondayBoardInventory, item_id: str) -> str:
    """Status de sistema Sunday (`done` vs `to_do`) pela semântica F2.1."""
    item = next((row for row in inventory.items if row.item_id == item_id), None)
    if item is None:
        return "to_do"
    group_title = inventory.groups.get(item.group_id or "")
    main_status = find_main_status_column(inventory)
    if item_is_concluded(
        group_title=group_title,
        status_labels=item.status_labels,
        main_status_column_id=main_status,
    ):
        return "done"
    return "to_do"


def _column_plan_by_monday_id(board_plan: BoardPlan) -> dict[str, object]:
    return {plan.monday_column_id: plan for plan in board_plan.column_plans}


def _sunday_column_by_id(snapshot: SundayBoardSnapshot) -> dict[str, object]:
    return {column.id: column for column in snapshot.columns}


def _status_key_for_label(
    board_plan: BoardPlan,
    monday_column_id: str,
    label: str | None,
) -> str | None:
    if not label:
        return None
    status_map = board_plan.status_mappings.get(monday_column_id, {})
    key = status_map.get(label)
    if key is None and label not in status_map:
        key = slugify_status_key(label)
    if key is None:
        raise ValueError(
            f"Status {label!r} na coluna {monday_column_id} sem mapping aprovado.",
        )
    return key


def _sunday_value_for_monday_column(
    *,
    monday_column: MondayColumnInfo,
    text: str | None,
    board_plan: BoardPlan,
) -> object | None:
    if not text:
        return None
    if monday_column.type == "status":
        key = _status_key_for_label(board_plan, monday_column.id, text)
        return key
    if monday_column.type == "numbers":
        try:
            return float(text.replace(",", "."))
        except ValueError:
            return None
    if monday_column.type == "date":
        return text[:10] if len(text) >= 10 else text
    if monday_column.type in {"text", "long_text", "link", "email", "location"}:
        return text
    return None


def apply_create_item(
    *,
    client,
    plan: ExecutionPlan,
    operation: PlannedOperation,
    inventory: MondayBoardInventory,
    board_plan: BoardPlan,
    sunday_snapshot: SundayBoardSnapshot,
    apply_source: MondayApplySource,
    monday_id_column_id: str,
    target_group_id: str,
    stats: ApplyWriteStats | None = None,
) -> str:
    """Cria um item Sunday (CREATE) com campos mapeados e verificação."""
    write_stats = stats or ApplyWriteStats()
    ledger_key = f"{plan.monday_board_id}:{operation.monday_item_id}"
    records = load_persistent_ledger(DEFAULT_LEDGER_PATH)
    if records.get(ledger_key, {}).get("migration_status") == "migrated":
        existing = records[ledger_key].get("sunday_item_id")
        if existing:
            return str(existing)

    created = client.create_item(
        plan.sunday_board_id,
        apply_source.name or f"Item {operation.monday_item_id}",
        group_id=target_group_id,
    )
    sunday_item_id = created.id
    write_stats.items_created += 1

    monday_id_value = format_monday_id_column_value(
        plan.monday_board_id, operation.monday_item_id,
    )
    client.set_custom_value(
        plan.sunday_board_id,
        sunday_item_id,
        monday_id_column_id,
        monday_id_value,
        verify=True,
    )
    write_stats.custom_values += 1

    if apply_source.name:
        client.update_item(
            plan.sunday_board_id,
            sunday_item_id,
            name=apply_source.name,
            verify=True,
        )
        write_stats.system_fields += 1

    system_status = derive_system_status_key(inventory, operation.monday_item_id)
    client.set_status(
        plan.sunday_board_id,
        sunday_item_id,
        system_status,
        verify=True,
    )
    write_stats.status_writes += 1
    write_stats.system_fields += 1

    column_plans = _column_plan_by_monday_id(board_plan)
    sunday_columns = _sunday_column_by_id(sunday_snapshot)
    for monday_column in inventory.columns:
        if monday_column.type in {
            "name", "subtasks", "mirror", "lookup", "item_id",
            "creation_log", "last_updated", "people", "file",
            "board_relation", "formula",
        }:
            continue
        plan_column = column_plans.get(monday_column.id)
        if plan_column is None or not plan_column.exists_in_target:
            continue
        if plan_column.strategy not in {"direto", "transformacao", "configurar_manualmente"}:
            continue
        sunday_column_id = plan_column.sunday_column_id
        if not sunday_column_id:
            continue
        sunday_column = sunday_columns.get(sunday_column_id)
        if sunday_column is None or sunday_column.is_system:
            continue
        text = apply_source.values_by_column_id.get(monday_column.id)
        value = _sunday_value_for_monday_column(
            monday_column=monday_column,
            text=text,
            board_plan=board_plan,
        )
        if value is None:
            continue
        client.set_custom_value(
            plan.sunday_board_id,
            sunday_item_id,
            sunday_column_id,
            value,
            verify=True,
        )
        write_stats.custom_values += 1
        if monday_column.type == "status":
            write_stats.status_writes += 1

    persisted = client.get_item(plan.sunday_board_id, sunday_item_id)
    if persisted is None:
        raise RuntimeError(f"Item {sunday_item_id} não encontrado após CREATE.")
    stored_monday_id = client.get_value(sunday_item_id, monday_id_column_id)
    if stored_monday_id != monday_id_value:
        raise RuntimeError(
            f"Monday ID não persistiu para item {operation.monday_item_id}: "
            f"{stored_monday_id!r} != {monday_id_value!r}",
        )
    return sunday_item_id


def verify_applied_board(
    *,
    client,
    plan: ExecutionPlan,
    inventory: MondayBoardInventory,
    board_plan: BoardPlan,
    apply_sources: dict[str, MondayApplySource],
    monday_id_column_id: str,
    target_group_id: str,
) -> FieldCheckReport:
    """Validação pós-APPLY item a item (somente leitura)."""
    report = FieldCheckReport()
    sunday_by_monday = build_sunday_monday_id_index(
        client,
        board_id=plan.sunday_board_id,
        monday_id_column_id=monday_id_column_id,
    )
    column_plans = _column_plan_by_monday_id(board_plan)

    for item in inventory.items:
        source = apply_sources.get(item.item_id)
        if source is None:
            report.total += 1
            report.errors.append(f"{item.item_id}: source Monday ausente")
            continue
        sunday_item_id = sunday_by_monday.get(item.item_id)
        if not sunday_item_id:
            report.total += 1
            report.errors.append(f"{item.item_id}: Sunday item não encontrado via Monday ID")
            continue

        def check(field: str, expected: object, actual: object) -> None:
            report.total += 1
            if expected == actual:
                report.ok += 1
            else:
                report.errors.append(
                    f"{item.item_id}/{field}: esperado {expected!r}, lido {actual!r}",
                )

        sunday_item = client.get_item(plan.sunday_board_id, sunday_item_id)
        expected_monday_id = format_monday_id_column_value(
            plan.monday_board_id, item.item_id,
        )
        check("name", source.name, sunday_item.name if sunday_item else None)
        check("group_id", target_group_id, sunday_item.group_id if sunday_item else None)
        check(
            "monday_id",
            expected_monday_id,
            client.get_value(sunday_item_id, monday_id_column_id),
        )
        check(
            "system_status",
            derive_system_status_key(inventory, item.item_id),
            sunday_item.status if sunday_item else None,
        )

        for monday_column in inventory.columns:
            if monday_column.type in {
                "name", "subtasks", "mirror", "lookup", "item_id",
                "creation_log", "last_updated", "people", "file",
                "board_relation", "formula",
            }:
                continue
            plan_column = column_plans.get(monday_column.id)
            if plan_column is None or not plan_column.exists_in_target:
                continue
            if plan_column.strategy not in {"direto", "transformacao", "configurar_manualmente"}:
                continue
            sunday_column_id = plan_column.sunday_column_id
            if not sunday_column_id:
                continue
            expected = _sunday_value_for_monday_column(
                monday_column=monday_column,
                text=source.values_by_column_id.get(monday_column.id),
                board_plan=board_plan,
            )
            if expected is None:
                continue
            actual = client.get_value(sunday_item_id, sunday_column_id)
            check(monday_column.title, expected, actual)

    return report
