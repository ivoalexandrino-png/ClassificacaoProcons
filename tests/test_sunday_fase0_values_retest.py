"""Testes offline dos helpers puros do reteste de values/board_relation do Sunday.

Não tocam a rede: exercitam guard-rail, extração de value, lookup de item e redação de PII.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "sunday_fase0_values_retest.py"
SPEC = importlib.util.spec_from_file_location("sunday_fase0_values_retest", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
retest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retest)


def test_should_allow_writes_only_on_authorized_sandbox_boards():
    retest.OWNED_ITEMS.clear()
    retest.OWNED_ITEMS.add("7666")

    # GET é sempre permitido
    retest._assert_write_allowed("GET", "/boards/79/items")
    # POST/PATCH nos boards de sandbox autorizados
    retest._assert_write_allowed("POST", "/boards/80/items")
    retest._assert_write_allowed("POST", "/boards/81/items")
    # PATCH em item criado por este reteste
    retest._assert_write_allowed("PATCH", "/boards/items/7666/values/456")


def test_should_block_writes_outside_sandbox_and_unowned_items():
    retest.OWNED_ITEMS.clear()
    retest.OWNED_ITEMS.add("7666")

    with pytest.raises(RuntimeError):
        retest._assert_write_allowed("POST", "/boards/79/items")  # board real, não sandbox
    with pytest.raises(RuntimeError):
        retest._assert_write_allowed("PATCH", "/boards/items/9999")  # item não criado aqui
    with pytest.raises(RuntimeError):
        retest._assert_write_allowed("DELETE", "/boards/groups/250")


def test_should_extract_value_by_column_id():
    values = [
        {"column_id": "453", "value": 12345},
        {"column_id": "456", "value": {"links": [{"item_id": "7655"}]}},
    ]
    assert retest._value_of(values, "453") == 12345
    assert retest._value_of(values, "456") == {"links": [{"item_id": "7655"}]}
    assert retest._value_of(values, "999") is None
    assert retest._value_of("não-é-lista", "453") is None


def test_should_find_item_by_id():
    items = [{"id": "7666", "name": "alvo"}, {"id": "7667", "name": "outro"}]
    assert retest._item_by_id(items, "7666") == {"id": "7666", "name": "alvo"}
    assert retest._item_by_id(items, "0000") is None
    assert retest._item_by_id(None, "7666") is None


def test_should_redact_token_and_user_identity_fields():
    retest.REDACT.clear()
    retest.REDACT.add("token-super-secreto")

    payload = {
        "name": "TESTE VALUES API - PODE EXCLUIR",  # nome de item: preservado
        "owner_user_id": "37",  # PII: redigido por chave
        "value": "token-super-secreto",  # segredo: redigido por match
        "links": [{"item_id": "7655"}],
    }
    sanitized = retest._redact(payload)

    assert sanitized["name"] == "TESTE VALUES API - PODE EXCLUIR"
    assert sanitized["owner_user_id"] == retest.IDENTITY_PLACEHOLDER
    assert sanitized["value"] == "<omitido: sensível>"
    assert sanitized["links"] == [{"item_id": "7655"}]


def test_should_collapse_auth_me_identity_body():
    body = {"id": "37", "user_type": "employee", "hierarchy_level": 10, "job_title": "X"}
    assert retest._redact(body) == "<omitido: dados de identidade do usuário>"
