"""Smoke de integração OPT-IN do Sunday — nunca roda no pytest padrão.

Só executa com `SUNDAY_INTEGRATION_SANDBOX=1` + secrets no ambiente, e faz apenas
LEITURA nos sandboxes autorizados (boards 80/81). Escritas reais ficam nos scripts
da Fase 0 (`scripts/sunday_fase0_*.py`), executadas sob autorização explícita.
"""

from __future__ import annotations

import os

import pytest

RUN_INTEGRATION = os.environ.get("SUNDAY_INTEGRATION_SANDBOX") == "1"
SANDBOX_BOARD_ID = "80"
SANDBOX_BOARD_NAME = "SANDBOX - API SUNDAY - NÃO USAR"

pytestmark = pytest.mark.skipif(
    not RUN_INTEGRATION or not os.environ.get("SUNDAY_API_TOKEN"),
    reason="integração opt-in: exige SUNDAY_INTEGRATION_SANDBOX=1 e SUNDAY_API_TOKEN",
)


def test_should_read_sandbox_board_when_integration_enabled():
    from classificacao_procons.sunday import SundayClient

    client = SundayClient()
    me = client.get_me()
    assert me.id

    board = client.get_board(SANDBOX_BOARD_ID)
    assert board.name == SANDBOX_BOARD_NAME

    columns = client.list_columns(SANDBOX_BOARD_ID)
    assert any(column.is_system for column in columns)

    result = client.list_items(SANDBOX_BOARD_ID)
    assert result.not_modified is False
