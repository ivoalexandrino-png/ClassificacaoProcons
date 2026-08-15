"""Integração: apply_writer + fetch adaptativo para lotes de 50 items."""

from __future__ import annotations

from classificacao_procons.migration.apply_writer import (
    _fetch_monday_updates,
    fetch_monday_apply_sources,
)


def _make_updates(item_id: str, count: int = 1) -> list[dict]:
    return [
        {
            "id": f"u-{item_id}-{index}",
            "text_body": f"body-{item_id}-{index}",
            "created_at": "2026-01-01T00:00:00Z",
            "creator": {"name": "Author"},
        }
        for index in range(count)
    ]


def test_apply_fetch_monday_updates_recovers_all_50_with_silent_truncation(monkeypatch):
    item_ids = {str(index) for index in range(1, 51)}
    graphql_calls: list[list[str]] = []

    def fake_graphql(*, api_token, query, variables=None):
        if "items_page" in query:
            return {
                "boards": [
                    {
                        "items_page": {
                            "cursor": None,
                            "items": [
                                {
                                    "id": item_id,
                                    "name": f"Item {item_id}",
                                    "group": {"id": "g1"},
                                    "column_values": [],
                                }
                                for item_id in sorted(item_ids)
                            ],
                        },
                    },
                ],
            }
        batch = list(variables["ids"])
        graphql_calls.append(batch)
        if len(batch) > 25:
            batch = batch[:25]
        return {
            "items": [
                {"id": item_id, "updates": _make_updates(item_id)}
                for item_id in batch
            ],
        }

    monkeypatch.setattr(
        "classificacao_procons.migration.apply_writer._graphql_request",
        fake_graphql,
    )
    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql,
    )

    updates_by_item = _fetch_monday_updates("token", item_ids)
    assert set(updates_by_item) == item_ids
    assert sum(len(values) for values in updates_by_item.values()) == 50
    assert len(graphql_calls) > 1


def test_fetch_monday_apply_sources_recovers_all_50_before_any_write(monkeypatch):
    item_ids = {str(index) for index in range(1, 51)}

    def fake_graphql(*, api_token, query, variables=None):
        if "items_page" in query:
            return {
                "boards": [
                    {
                        "items_page": {
                            "cursor": None,
                            "items": [
                                {
                                    "id": item_id,
                                    "name": f"Item {item_id}",
                                    "group": {"id": "g1"},
                                    "column_values": [],
                                }
                                for item_id in sorted(item_ids)
                            ],
                        },
                    },
                ],
            }
        batch = list(variables["ids"])
        if len(batch) > 25:
            batch = batch[:25]
        return {
            "items": [
                {"id": item_id, "updates": _make_updates(item_id, count=2)}
                for item_id in batch
            ],
        }

    monkeypatch.setattr(
        "classificacao_procons.migration.apply_writer._graphql_request",
        fake_graphql,
    )
    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql,
    )

    sources = fetch_monday_apply_sources("token", "4944254220", item_ids=item_ids)
    assert set(sources) == item_ids
    assert all(len(source.updates) == 2 for source in sources.values())
