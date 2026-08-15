from __future__ import annotations

from types import SimpleNamespace

import pytest

from classificacao_procons.migration import apply_writer, monday_inventory
from classificacao_procons.migration.apply_writer import (
    ApplyWriteStats,
    MondayUpdateSource,
    _fetch_monday_updates,
    _verify_created_item_visible,
    format_monday_update_comment,
    migrate_monday_updates,
)
from classificacao_procons.migration.executor import comment_idempotency_marker
from classificacao_procons.sunday.models import Comment


def _comment(body: str) -> Comment:
    return Comment.from_payload({"id": "comment-id", "body": body})


class CommentClient:
    def __init__(
        self,
        *,
        existing: list[str] | None = None,
        visible_after_reads: int = 0,
        never_persist: bool = False,
    ):
        self.bodies = list(existing or [])
        self.created: list[str] = []
        self.visible_after_reads = visible_after_reads
        self.never_persist = never_persist
        self.reads_after_create = 0

    def list_comments(self, item_id: str):
        assert item_id == "sunday-item"
        visible = list(self.bodies)
        if self.created:
            self.reads_after_create += 1
            if (
                not self.never_persist
                and self.reads_after_create > self.visible_after_reads
            ):
                visible.extend(self.created)
        return [_comment(body) for body in visible]

    def add_comment(self, item_id: str, body: str):
        assert item_id == "sunday-item"
        self.created.append(body)
        return _comment(body)


def _update(**overrides) -> MondayUpdateSource:
    values = {
        "update_id": "update-7",
        "body": "Operational migration note.",
        "author_name": None,
        "created_at": None,
    }
    values.update(overrides)
    return MondayUpdateSource(**values)


def test_comment_marker_and_body_are_deterministic_without_false_attribution():
    update = _update()
    body = format_monday_update_comment("item-3", update)

    assert body == (
        "[Histórico importado do Monday]\n\nOperational migration note.\n\n"
        "[monday-migracao:item-3:update-7]"
    )
    assert "autor:" not in body
    assert "data:" not in body
    assert body == format_monday_update_comment("item-3", update)


def test_comment_preserves_available_author_and_date():
    update = _update(
        author_name="Migration Operator",
        created_at="2026-08-01T12:00:00Z",
    )

    body = format_monday_update_comment("item-3", update)

    assert "autor original: Migration Operator" in body
    assert "data original: 2026-08-01T12:00:00Z" in body
    assert "Operational migration note." in body


def test_existing_marker_is_skipped_before_write():
    marker = comment_idempotency_marker("item-3", "update-7")
    client = CommentClient(existing=[f"Already migrated\n\n{marker}"])
    stats = ApplyWriteStats()

    migrate_monday_updates(
        client=client,
        sunday_item_id="sunday-item",
        monday_item_id="item-3",
        updates=(_update(),),
        expected_update_ids=("update-7",),
        stats=stats,
    )

    assert client.created == []
    assert stats.comments == 0


def test_comment_readback_retries_until_marker_is_visible():
    client = CommentClient(visible_after_reads=2)
    stats = ApplyWriteStats()

    migrate_monday_updates(
        client=client,
        sunday_item_id="sunday-item",
        monday_item_id="item-3",
        updates=(_update(),),
        expected_update_ids=("update-7",),
        stats=stats,
    )

    assert len(client.created) == 1
    assert client.reads_after_create == 4  # 3 tentativas + validação final
    assert stats.comments == 1


def test_comment_readback_failure_is_mandatory_and_fail_fast():
    client = CommentClient(never_persist=True)

    with pytest.raises(RuntimeError, match="não persistiu"):
        migrate_monday_updates(
            client=client,
            sunday_item_id="sunday-item",
            monday_item_id="item-3",
            updates=(_update(),),
            expected_update_ids=("update-7",),
            stats=ApplyWriteStats(),
        )

    assert len(client.created) == 1


def test_apply_aborts_if_exact_plan_updates_changed():
    with pytest.raises(RuntimeError, match="PLAN=2, APPLY=1"):
        migrate_monday_updates(
            client=SimpleNamespace(),
            sunday_item_id="sunday-item",
            monday_item_id="item-3",
            updates=(_update(),),
            expected_update_ids=("update-7", "update-8"),
            stats=ApplyWriteStats(),
        )


def test_read_only_update_diagnostic_paginates_to_exact_count(monkeypatch):
    calls: list[int] = []

    def fake_graphql_request(*, api_token, query, variables):
        assert api_token == "test-token"
        assert query == monday_inventory._ITEM_UPDATES_PAGE_QUERY
        page = variables["page"]
        calls.append(page)
        count = 100 if page == 1 else 1
        return {
            "items": [
                {
                    "id": "item-3",
                    "updates": [
                        {
                            "id": f"update-{page}-{index}",
                            "text_body": "Operational migration note.",
                        }
                        for index in range(count)
                    ],
                },
            ],
        }

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql_request,
    )

    assert monday_inventory._fetch_exact_update_counts(
        "test-token",
        ["item-3"],
    ) == {"item-3": 101}
    assert calls == [1, 2]


def test_two_legitimate_updates_are_both_migratable():
    updates = [
        {
            "id": "update-1",
            "text_body": "First operational note.",
            "created_at": "2026-08-01T12:00:00Z",
            "creator": {"id": "author-1"},
        },
        {
            "id": "update-2",
            "text_body": "Second operational note.",
            "created_at": "2026-08-02T12:00:00Z",
            "creator": {"id": "author-2"},
        },
    ]

    diagnostics = [monday_inventory._classify_update(update) for update in updates]

    assert [update.is_migratable for update in diagnostics] == [True, True]
    assert [update.classification for update in diagnostics] == [
        "text_update_with_author",
        "text_update_with_author",
    ]


def test_empty_update_is_excluded_with_explicit_reason():
    diagnostic = monday_inventory._classify_update(
        {
            "id": "update-empty",
            "text_body": "  ",
            "created_at": "2026-08-01T12:00:00Z",
            "creator": {"id": "author-1"},
        },
    )

    assert diagnostic.is_migratable is False
    assert diagnostic.classification == "empty_update"
    assert diagnostic.exclusion_reason == "empty_body"


def test_apply_source_reads_body_author_and_date_without_writes(monkeypatch):
    def fake_graphql_request(*, api_token, query, variables):
        assert api_token == "test-token"
        assert query == apply_writer._APPLY_UPDATES_QUERY
        return {
            "items": [
                {
                    "id": "item-3",
                    "updates": [
                        {
                            "id": "update-7",
                            "text_body": "Operational migration note.",
                            "created_at": "2026-08-01T12:00:00Z",
                            "creator": {"name": "Migration Operator"},
                        },
                    ],
                },
            ],
        }

    monkeypatch.setattr(
        "classificacao_procons.migration.monday_items_fetch._graphql_request",
        fake_graphql_request,
    )

    updates = _fetch_monday_updates("test-token", {"item-3"})["item-3"]
    assert updates == (
        MondayUpdateSource(
            update_id="update-7",
            body="Operational migration note.",
            author_name="Migration Operator",
            created_at="2026-08-01T12:00:00Z",
        ),
    )


def test_comment_formatter_does_not_inject_environment_secret(monkeypatch):
    secret = "sunday-secret-never-in-comment"
    monkeypatch.setenv("SUNDAY_API_TOKEN_TEST", secret)

    body = format_monday_update_comment("item-3", _update())

    assert secret not in body


def test_item_readback_retries_after_creation():
    class ItemClient:
        reads = 0

        def get_item(self, board_id, item_id):
            assert (board_id, item_id) == ("board-id", "sunday-item")
            self.reads += 1
            return object() if self.reads == 3 else None

    client = ItemClient()
    _verify_created_item_visible(client, "board-id", "sunday-item")
    assert client.reads == 3
