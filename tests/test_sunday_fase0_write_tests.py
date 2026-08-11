from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "sunday_fase0_write_tests.py"
SPEC = importlib.util.spec_from_file_location("sunday_fase0_write_tests", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
sunday_write_tests = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sunday_write_tests)


def test_should_redact_sensitive_headers_and_token_occurrences(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SUNDAY_API_TOKEN", "token-super-secreto")

    sanitized = sunday_write_tests._sanitize(
        {
            "headers": {
                "Authorization": "Bearer outro-segredo",
                "Cookie": "session=segredo",
                "X-Sunday-Token": "token-super-secreto",
                "Content-Type": "application/json",
            },
            "body": "prefixo token-super-secreto sufixo",
        },
    )

    assert sanitized == {
        "headers": {
            "Content-Type": "application/json",
        },
        "body": "prefixo [REDACTED] sufixo",
    }


def test_should_remove_private_identity_fields():
    sanitized = sunday_write_tests._sanitize(
        {
            "id": "test-resource",
            "creator_user_id": "real-user",
            "author_name": "Real Name",
            "members": [{"email": "real@example.com"}],
        },
    )

    assert sanitized == {"id": "test-resource"}


def test_should_keep_only_safe_webhook_headers():
    sanitized = sunday_write_tests._sanitize_entry(
        {
            "note": "T8 entregas com endpoint 200",
            "deliveries": [
                {
                    "headers": {
                        "content-type": ["application/json"],
                        "user-agent": ["node"],
                        "x-forwarded-for": ["192.0.2.1"],
                        "x-internal-header": ["private"],
                    },
                },
            ],
        },
    )

    assert sanitized == {
        "note": "T8 entregas com endpoint 200",
        "deliveries": [
            {
                "headers": {
                    "content-type": ["application/json"],
                    "user-agent": ["node"],
                },
            },
        ],
    }


def test_should_allow_only_the_authorized_relation_board_payload():
    authorized_payload = {
        "name": sunday_write_tests.RELATION_BOARD_NAME,
        "description": "Sandbox de teste de board_relation. Pode apagar.",
        "template_key": "board",
        "workspace_id": sunday_write_tests.WORKSPACE_ID,
    }

    sunday_write_tests._assert_write_allowed("POST", "/boards", authorized_payload)

    with pytest.raises(
        sunday_write_tests.GuardrailError,
        match="Criação de board fora do sandbox RELATION bloqueada",
    ):
        sunday_write_tests._assert_write_allowed(
            "POST",
            "/boards",
            {**authorized_payload, "workspace_id": "999"},
        )


def test_should_block_direct_board_mutations_except_hierarchy_configuration():
    sunday_write_tests._assert_write_allowed(
        "PATCH",
        f"/boards/{sunday_write_tests.SANDBOX_BOARD_ID}",
        {"hierarchy_depth": 2},
    )

    with pytest.raises(
        sunday_write_tests.GuardrailError,
        match="Mutação direta do board bloqueada",
    ):
        sunday_write_tests._assert_write_allowed(
            "DELETE",
            f"/boards/{sunday_write_tests.SANDBOX_BOARD_ID}",
        )


def test_should_block_mutation_of_unowned_item():
    with pytest.raises(
        sunday_write_tests.GuardrailError,
        match="Escrita bloqueada pelo guard-rail",
    ):
        sunday_write_tests._assert_write_allowed(
            "PATCH",
            "/boards/items/real-item",
            {"name": "não permitido"},
        )
