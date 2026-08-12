"""Escritor APPLY da migração Monday → Sunday (Fase 3).

Somente operações CREATE com verificação por item. Não conhece domínios além do
contrato genérico: inventário Monday, BoardPlan, snapshot Sunday e SundayClient.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from classificacao_procons.migration.executor import (
    ExecutionPlan,
    PlannedOperation,
    comment_idempotency_marker,
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

_APPLY_UPDATES_QUERY = """
query ($ids: [ID!], $limit: Int!, $page: Int!) {
  items(ids: $ids) {
    id
    updates(limit: $limit, page: $page) {
      id
      body
      text_body
      created_at
      creator { name }
    }
  }
}
"""

UPDATES_PAGE_SIZE = 100
READ_BACK_ATTEMPTS = 3


@dataclass(frozen=True)
class MondayUpdateSource:
    update_id: str
    body: str
    author_name: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class MondayApplySource:
    item_id: str
    name: str
    group_id: str | None
    values_by_column_id: dict[str, str | None]  # text ou label de status
    updates: tuple[MondayUpdateSource, ...] = ()


@dataclass
class ApplyWriteStats:
    items_created: int = 0
    system_fields: int = 0
    custom_values: int = 0
    status_writes: int = 0
    comments: int = 0
    comments_skipped: int = 0
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
    if not sources:
        return sources
    updates_by_item = _fetch_monday_updates(api_token, set(sources))
    return {
        item_id: MondayApplySource(
            item_id=source.item_id,
            name=source.name,
            group_id=source.group_id,
            values_by_column_id=source.values_by_column_id,
            updates=updates_by_item[item_id],
        )
        for item_id, source in sources.items()
    }


def _fetch_monday_updates(
    api_token: str,
    item_ids: set[str],
) -> dict[str, tuple[MondayUpdateSource, ...]]:
    result: dict[str, list[MondayUpdateSource]] = {
        item_id: [] for item_id in sorted(item_ids)
    }
    ordered_ids = sorted(item_ids)
    for offset in range(0, len(ordered_ids), 100):
        batch = ordered_ids[offset : offset + 100]
        page_number = 1
        while True:
            rows = _graphql_request(
                api_token=api_token,
                query=_APPLY_UPDATES_QUERY,
                variables={
                    "ids": batch,
                    "limit": UPDATES_PAGE_SIZE,
                    "page": page_number,
                },
            ).get("items", [])
            by_id = {str(row.get("id")): row for row in rows}
            missing = set(batch) - set(by_id)
            if missing:
                raise RuntimeError(
                    f"Leitura de updates incompleta para {len(missing)} item(ns).",
                )
            page_full = False
            for item_id in batch:
                updates = by_id[item_id].get("updates") or []
                page_full = page_full or len(updates) == UPDATES_PAGE_SIZE
                for update in updates:
                    update_id = str(update.get("id") or "").strip()
                    body = str(
                        update.get("text_body") or update.get("body") or "",
                    ).strip()
                    if not update_id or not body:
                        continue
                    creator = update.get("creator")
                    author = (
                        str(creator.get("name") or "").strip()
                        if isinstance(creator, dict)
                        else ""
                    )
                    created_at = str(update.get("created_at") or "").strip()
                    result[item_id].append(
                        MondayUpdateSource(
                            update_id=update_id,
                            body=body,
                            author_name=author or None,
                            created_at=created_at or None,
                        ),
                    )
            if not page_full:
                break
            page_number += 1
    return {item_id: tuple(updates) for item_id, updates in result.items()}


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


def build_sunday_comment_marker_index(
    client,
    *,
    monday_id_index: dict[str, str],
    inventory: MondayBoardInventory,
) -> dict[str, set[str]]:
    """Lê somente markers esperados, sem reter conteúdo dos comments Sunday."""
    diagnostics_by_item = {
        item.item_id: item.update_diagnostics for item in inventory.items
    }
    result: dict[str, set[str]] = {}
    for monday_item_id, sunday_item_id in monday_id_index.items():
        expected = {
            comment_idempotency_marker(monday_item_id, update.update_id)
            for update in diagnostics_by_item.get(monday_item_id, ())
            if update.is_migratable
        }
        if not expected:
            result[monday_item_id] = set()
            continue
        existing: set[str] = set()
        for comment in client.list_comments(sunday_item_id):
            existing.update(
                line.strip()
                for line in comment.body.splitlines()
                if line.strip() in expected
            )
        result[monday_item_id] = existing
    return result


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


def format_monday_update_comment(
    monday_item_id: str,
    update: MondayUpdateSource,
) -> str:
    """Preserva conteúdo e só declara autor/data quando a origem os forneceu."""
    metadata = ["Histórico importado do Monday"]
    if update.author_name:
        metadata.append(f"autor original: {' '.join(update.author_name.split())}")
    if update.created_at:
        metadata.append(f"data original: {' '.join(update.created_at.split())}")
    marker = comment_idempotency_marker(monday_item_id, update.update_id)
    return f"[{' · '.join(metadata)}]\n\n{update.body}\n\n{marker}"


def _comment_marker_present(client, sunday_item_id: str, marker: str) -> bool:
    return any(
        marker in {line.strip() for line in comment.body.splitlines()}
        for comment in client.list_comments(sunday_item_id)
    )


def migrate_monday_updates(
    *,
    client,
    sunday_item_id: str,
    monday_item_id: str,
    updates: tuple[MondayUpdateSource, ...],
    expected_update_ids: tuple[str, ...],
    stats: ApplyWriteStats,
) -> None:
    """Cria comments idempotentes e exige confirmação por releitura."""
    expected_ids = tuple(sorted(expected_update_ids))
    actual_ids = tuple(sorted(update.update_id for update in updates))
    if actual_ids != expected_ids:
        raise RuntimeError(
            f"Updates mudaram para item {monday_item_id}: "
            f"PLAN={len(expected_ids)}, APPLY={len(actual_ids)}.",
        )
    for update in sorted(
        updates,
        key=lambda source: (source.created_at or "", source.update_id),
    ):
        marker = comment_idempotency_marker(monday_item_id, update.update_id)
        if _comment_marker_present(client, sunday_item_id, marker):
            stats.comments_skipped += 1
            continue
        client.add_comment(
            sunday_item_id,
            format_monday_update_comment(monday_item_id, update),
        )
        for _attempt in range(READ_BACK_ATTEMPTS):
            if _comment_marker_present(client, sunday_item_id, marker):
                stats.comments += 1
                break
        else:
            raise RuntimeError(
                f"Comment {marker} não persistiu após releitura do item "
                f"{sunday_item_id}.",
            )
    missing_markers = [
        comment_idempotency_marker(monday_item_id, update_id)
        for update_id in expected_ids
        if not _comment_marker_present(
            client,
            sunday_item_id,
            comment_idempotency_marker(monday_item_id, update_id),
        )
    ]
    if missing_markers:
        raise RuntimeError(
            f"Validação final encontrou {len(missing_markers)} comment(s) ausente(s) "
            f"no item {sunday_item_id}.",
        )


def _verify_created_item_visible(client, board_id: str, item_id: str) -> None:
    for _attempt in range(READ_BACK_ATTEMPTS):
        if client.get_item(board_id, item_id) is not None:
            return
    raise RuntimeError(f"Item {item_id} não encontrado após CREATE.")


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
    created = client.create_item(
        plan.sunday_board_id,
        apply_source.name or f"Item {operation.monday_item_id}",
        group_id=target_group_id,
    )
    sunday_item_id = created.id
    write_stats.items_created += 1
    _verify_created_item_visible(client, plan.sunday_board_id, sunday_item_id)

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

    stored_monday_id = client.get_value(sunday_item_id, monday_id_column_id)
    if stored_monday_id != monday_id_value:
        raise RuntimeError(
            f"Monday ID não persistiu para item {operation.monday_item_id}: "
            f"{stored_monday_id!r} != {monday_id_value!r}",
        )
    migrate_monday_updates(
        client=client,
        sunday_item_id=sunday_item_id,
        monday_item_id=operation.monday_item_id,
        updates=apply_source.updates,
        expected_update_ids=tuple(
            update.update_id
            for update in operation.update_diagnostics
            if update.is_migratable
        ),
        stats=write_stats,
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
