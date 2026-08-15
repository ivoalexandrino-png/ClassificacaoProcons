"""Testes do fetch adaptativo items(ids:) — completude e subdivisão."""

from __future__ import annotations

import pytest

from classificacao_procons.migration.monday_inventory import _fetch_update_diagnostics
from classificacao_procons.migration.monday_items_fetch import (
    ITEM_IDS_QUERY_INITIAL_BATCH,
    _fetch_items_by_ids_adaptive,
    validate_items_fetch_completeness,
)


def test_validate_items_fetch_completeness_detects_missing_and_ok():
    complete = validate_items_fetch_completeness(["1", "2"], {"1": {}, "2": {}})
    assert complete.is_complete
    assert complete.missing_ids == ()
    assert complete.duplicate_ids == ()

    partial = validate_items_fetch_completeness(["1", "2", "3"], {"1": {}, "3": {}})
    assert not partial.is_complete
    assert partial.missing_ids == ("2",)


def test_fetch_items_by_ids_adaptive_complete_batch(monkeypatch):
    calls: list[list[str]] = []

    def fake_graphql(*, api_token, query, variables=None):
        calls.append(list(variables["ids"]))
        return {
            "items": [{"id": item_id, "updates": []} for item_id in variables["ids"]],
        }

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql,
    )
    item_ids = [str(i) for i in range(1, 6)]
    result = _fetch_items_by_ids_adaptive(
        "token",
        item_ids,
        query="Q",
        variables_for_batch=lambda batch: {"ids": batch},
    )
    assert set(result) == set(item_ids)
    assert len(calls) == 1


def test_fetch_items_by_ids_adaptive_subdivides_partial_batch(monkeypatch):
    calls: list[list[str]] = []

    def fake_graphql(*, api_token, query, variables=None):
        batch = variables["ids"]
        calls.append(list(batch))
        if len(batch) > 2:
            # Simula truncamento silencioso da API Monday.
            batch = batch[:2]
        return {"items": [{"id": item_id, "updates": []} for item_id in batch]}

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql,
    )
    item_ids = [str(i) for i in range(1, 9)]
    result = _fetch_items_by_ids_adaptive(
        "token",
        item_ids,
        query="Q",
        variables_for_batch=lambda batch: {"ids": batch},
    )
    assert set(result) == set(item_ids)
    assert len(calls) > 1


def test_fetch_items_by_ids_adaptive_raises_when_single_id_missing(monkeypatch):
    def fake_graphql(*, api_token, query, variables=None):
        return {"items": []}

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql,
    )
    with pytest.raises(RuntimeError, match="não retornou item solicitado"):
        _fetch_items_by_ids_adaptive(
            "token",
            ["999"],
            query="Q",
            variables_for_batch=lambda batch: {"ids": batch},
        )


def test_fetch_update_diagnostics_no_items_lost_with_partial_api(monkeypatch):
    page_calls: list[tuple[list[str], int]] = []

    def fake_graphql(*, api_token, query, variables=None):
        batch = variables["ids"]
        page = variables.get("page", 1)
        page_calls.append((list(batch), page))
        if len(batch) > 2:
            batch = batch[:2]
        return {
            "items": [
                {
                    "id": item_id,
                    "updates": [
                        {
                            "id": f"u-{item_id}",
                            "text_body": f"body-{item_id}",
                            "created_at": "2026-01-01T00:00:00Z",
                            "creator": {"id": "author-1"},
                        },
                    ],
                }
                for item_id in batch
            ],
        }

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql,
    )
    item_ids = [str(i) for i in range(1, 151)]
    diagnostics = _fetch_update_diagnostics("token", item_ids)
    assert set(diagnostics) == set(item_ids)
    assert all(len(values) == 1 for values in diagnostics.values())
    assert len(page_calls) > 1


def test_fetch_update_diagnostics_deduplicates_repeated_updates(monkeypatch):
    def fake_graphql(*, api_token, query, variables=None):
        return {
            "items": [
                {
                    "id": variables["ids"][0],
                    "updates": [
                        {
                            "id": "dup",
                            "text_body": "same",
                            "created_at": "2026-01-01T00:00:00Z",
                            "creator": {"id": "1"},
                        },
                        {
                            "id": "dup",
                            "text_body": "same again",
                            "created_at": "2026-01-02T00:00:00Z",
                            "creator": {"id": "1"},
                        },
                    ],
                },
            ],
        }

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql,
    )
    diagnostics = _fetch_update_diagnostics("token", ["42"])
    assert len(diagnostics["42"]) == 1


def test_initial_batch_size_documents_monday_truncation_threshold():
    assert ITEM_IDS_QUERY_INITIAL_BATCH == 100
