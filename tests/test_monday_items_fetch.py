"""Testes do fetch canônico adaptativo ``items(ids:)`` — completude e subdivisão."""

from __future__ import annotations

import pytest

from classificacao_procons.migration.monday_items_fetch import (
    ITEM_IDS_QUERY_INITIAL_BATCH,
    fetch_monday_items_by_ids_complete,
    validate_items_fetch_completeness,
)


def test_validate_items_fetch_completeness_detects_missing_and_ok():
    complete = validate_items_fetch_completeness(["1", "2"], {"1": {}, "2": {}})
    assert complete.is_complete
    assert complete.missing_ids == ()
    assert complete.duplicate_ids == ()
    assert complete.unexpected_ids == ()

    partial = validate_items_fetch_completeness(["1", "2", "3"], {"1": {}, "3": {}})
    assert not partial.is_complete
    assert partial.missing_ids == ("2",)


def test_validate_items_fetch_completeness_detects_unexpected_ids():
    result = validate_items_fetch_completeness(["1", "2"], {"1": {}, "2": {}, "99": {}})
    assert not result.is_complete
    assert result.unexpected_ids == ("99",)


def test_fetch_monday_items_by_ids_complete_batch(monkeypatch):
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
    result = fetch_monday_items_by_ids_complete(
        "token",
        item_ids,
        query="Q",
        variables_for_batch=lambda batch: {"ids": batch},
    )
    assert set(result) == set(item_ids)
    assert len(calls) == 1


def test_fetch_monday_items_by_ids_complete_subdivides_when_100_returns_25(monkeypatch):
    calls: list[list[str]] = []

    def fake_graphql(*, api_token, query, variables=None):
        batch = variables["ids"]
        calls.append(list(batch))
        if len(batch) > 25:
            batch = batch[:25]
        return {"items": [{"id": item_id, "updates": []} for item_id in batch]}

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql,
    )
    item_ids = [str(i) for i in range(1, 101)]
    result = fetch_monday_items_by_ids_complete(
        "token",
        item_ids,
        query="Q",
        variables_for_batch=lambda batch: {"ids": batch},
    )
    assert set(result) == set(item_ids)
    assert len(calls) > 1


def test_fetch_monday_items_by_ids_complete_subdivides_when_50_returns_25(monkeypatch):
    calls: list[list[str]] = []

    def fake_graphql(*, api_token, query, variables=None):
        batch = variables["ids"]
        calls.append(list(batch))
        if len(batch) > 25:
            batch = batch[:25]
        return {"items": [{"id": item_id, "updates": []} for item_id in batch]}

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql,
    )
    item_ids = [str(i) for i in range(1, 51)]
    result = fetch_monday_items_by_ids_complete(
        "token",
        item_ids,
        query="Q",
        variables_for_batch=lambda batch: {"ids": batch},
    )
    assert set(result) == set(item_ids)
    assert len(calls) > 1


def test_fetch_monday_items_by_ids_complete_subdivides_partial_batch(monkeypatch):
    calls: list[list[str]] = []

    def fake_graphql(*, api_token, query, variables=None):
        batch = variables["ids"]
        calls.append(list(batch))
        if len(batch) > 2:
            batch = batch[:2]
        return {"items": [{"id": item_id, "updates": []} for item_id in batch]}

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql,
    )
    item_ids = [str(i) for i in range(1, 9)]
    result = fetch_monday_items_by_ids_complete(
        "token",
        item_ids,
        query="Q",
        variables_for_batch=lambda batch: {"ids": batch},
    )
    assert set(result) == set(item_ids)
    assert len(calls) > 1


def test_fetch_monday_items_by_ids_complete_raises_when_single_id_missing(monkeypatch):
    def fake_graphql(*, api_token, query, variables=None):
        return {"items": []}

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql,
    )
    with pytest.raises(RuntimeError, match="não retornou item solicitado"):
        fetch_monday_items_by_ids_complete(
            "token",
            ["999"],
            query="Q",
            variables_for_batch=lambda batch: {"ids": batch},
        )


def test_fetch_monday_items_by_ids_complete_raises_on_duplicate_row(monkeypatch):
    def fake_graphql(*, api_token, query, variables=None):
        return {
            "items": [
                {"id": "1", "updates": []},
                {"id": "1", "updates": []},
            ],
        }

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql,
    )
    with pytest.raises(RuntimeError, match="duplicados"):
        fetch_monday_items_by_ids_complete(
            "token",
            ["1"],
            query="Q",
            variables_for_batch=lambda batch: {"ids": batch},
        )


def test_fetch_monday_items_by_ids_complete_raises_on_unexpected_id(monkeypatch):
    def fake_graphql(*, api_token, query, variables=None):
        return {
            "items": [
                {"id": "1", "updates": []},
                {"id": "999", "updates": []},
            ],
        }

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql,
    )
    with pytest.raises(RuntimeError, match="incompleto|inesperados"):
        fetch_monday_items_by_ids_complete(
            "token",
            ["1"],
            query="Q",
            variables_for_batch=lambda batch: {"ids": batch},
        )


def test_fetch_monday_items_by_ids_complete_result_is_deterministic(monkeypatch):
    call_count = {"n": 0}

    def fake_graphql(*, api_token, query, variables=None):
        call_count["n"] += 1
        batch = variables["ids"]
        if len(batch) > 2:
            batch = batch[:2]
        return {"items": [{"id": item_id, "updates": []} for item_id in batch]}

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql,
    )
    item_ids = [str(i) for i in range(1, 9)]
    first = fetch_monday_items_by_ids_complete(
        "token",
        item_ids,
        query="Q",
        variables_for_batch=lambda batch: {"ids": batch},
    )
    second = fetch_monday_items_by_ids_complete(
        "token",
        list(reversed(item_ids)),
        query="Q",
        variables_for_batch=lambda batch: {"ids": batch},
    )
    assert set(first) == set(second) == set(item_ids)
    assert call_count["n"] >= 2


def test_initial_batch_size_documents_monday_truncation_threshold():
    assert ITEM_IDS_QUERY_INITIAL_BATCH == 100


def test_root_cause_naive_fetch_detects_silent_truncation():
    """Documenta o comportamento fail-closed da implementação anterior."""
    batch = [str(i) for i in range(1, 51)]
    returned_rows = [{"id": item_id} for item_id in batch[:25]]
    by_id = {str(row["id"]): row for row in returned_rows}
    completeness = validate_items_fetch_completeness(batch, by_id)
    assert completeness.requested_ids == tuple(batch)
    assert len(completeness.returned_unique_ids) == 25
    assert len(completeness.missing_ids) == 25
    assert completeness.duplicate_ids == ()
    assert not completeness.is_complete
