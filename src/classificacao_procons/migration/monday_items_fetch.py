"""Fetch canônico e fail-closed de ``items(ids:)`` na API GraphQL do Monday.

A API pode truncar silenciosamente lotes grandes (HTTP/GraphQL 200 com resposta
parcial). Este módulo subdivide batches deterministicamente até cobertura
completa ou erro explícito.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from classificacao_procons.monday.client import _graphql_request

ITEM_IDS_QUERY_INITIAL_BATCH = 100


@dataclass(frozen=True)
class ItemsFetchCompleteness:
    """Metadados de completude de um fetch ``items(ids:)`` (somente IDs técnicos)."""

    requested_ids: tuple[str, ...]
    returned_unique_ids: tuple[str, ...]
    missing_ids: tuple[str, ...]
    duplicate_ids: tuple[str, ...]
    unexpected_ids: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        return (
            not self.missing_ids
            and not self.duplicate_ids
            and not self.unexpected_ids
        )


def validate_items_fetch_completeness(
    requested_ids: list[str] | tuple[str, ...],
    returned_by_id: dict[str, object],
) -> ItemsFetchCompleteness:
    """Valida cobertura exata: todos solicitados, sem duplicatas nem extras."""
    requested = tuple(requested_ids)
    requested_set = set(requested)
    seen: dict[str, int] = {}
    for item_id in returned_by_id:
        seen[item_id] = seen.get(item_id, 0) + 1
    duplicate_ids = tuple(item_id for item_id, count in seen.items() if count > 1)
    returned_unique = tuple(dict.fromkeys(returned_by_id))
    missing_ids = tuple(item_id for item_id in requested if item_id not in returned_by_id)
    unexpected_ids = tuple(
        item_id for item_id in returned_by_id if item_id not in requested_set
    )
    return ItemsFetchCompleteness(
        requested_ids=requested,
        returned_unique_ids=returned_unique,
        missing_ids=missing_ids,
        duplicate_ids=duplicate_ids,
        unexpected_ids=unexpected_ids,
    )


def _rows_to_by_id(rows: list[object]) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    duplicate_ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("id") or "").strip()
        if not item_id:
            continue
        if item_id in by_id:
            duplicate_ids.append(item_id)
            continue
        by_id[item_id] = row
    if duplicate_ids:
        unique_dupes = tuple(dict.fromkeys(duplicate_ids))
        raise RuntimeError(
            "Monday items(ids:) retornou IDs duplicados na mesma resposta: "
            f"{len(unique_dupes)} item(ns).",
        )
    return by_id


def fetch_monday_items_by_ids_complete(
    api_token: str,
    item_ids: list[str],
    *,
    query: str,
    variables_for_batch: Callable[[list[str]], dict],
) -> dict[str, dict]:
    """Busca ``items(ids:)`` com subdivisão adaptativa até cobertura completa."""
    if not item_ids:
        return {}

    results: dict[str, dict] = {}

    def fetch_batch(batch: list[str]) -> dict[str, dict]:
        rows = _graphql_request(
            api_token=api_token,
            query=query,
            variables=variables_for_batch(batch),
        ).get("items", [])
        by_id = _rows_to_by_id(rows if isinstance(rows, list) else [])
        completeness = validate_items_fetch_completeness(batch, by_id)
        if completeness.unexpected_ids:
            raise RuntimeError(
                "Monday items(ids:) retornou IDs inesperados: "
                f"{len(completeness.unexpected_ids)} item(ns).",
            )
        if completeness.is_complete:
            return by_id
        if len(batch) == 1:
            missing = completeness.missing_ids[0] if completeness.missing_ids else batch[0]
            raise RuntimeError(
                "Monday items(ids:) não retornou item solicitado "
                f"({missing}); resposta parcial não aceita.",
            )
        midpoint = len(batch) // 2
        left = fetch_batch(batch[:midpoint])
        right = fetch_batch(batch[midpoint:])
        merged = {**left, **right}
        merged_completeness = validate_items_fetch_completeness(batch, merged)
        if not merged_completeness.is_complete:
            raise RuntimeError(
                "Diagnóstico de items(ids:) incompleto após subdivisão: "
                f"{len(merged_completeness.missing_ids)} item(ns) ausente(s).",
            )
        return merged

    for offset in range(0, len(item_ids), ITEM_IDS_QUERY_INITIAL_BATCH):
        seed = item_ids[offset : offset + ITEM_IDS_QUERY_INITIAL_BATCH]
        results.update(fetch_batch(seed))

    final = validate_items_fetch_completeness(item_ids, results)
    if not final.is_complete:
        raise RuntimeError(
            "Inventário Monday incompleto: "
            f"{len(final.missing_ids)} ausente(s), "
            f"{len(final.duplicate_ids)} duplicado(s), "
            f"{len(final.unexpected_ids)} inesperado(s).",
        )
    return results


# Alias interno legado — preferir fetch_monday_items_by_ids_complete.
_fetch_items_by_ids_adaptive = fetch_monday_items_by_ids_complete
