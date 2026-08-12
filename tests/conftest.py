"""Fixtures compartilhados dos testes."""

from __future__ import annotations

import pytest

from classificacao_procons.contratos.controle_write_policy import ENV_CONTROLE_WRITE_ENABLED

_WRITE_POLICY_MODULES = frozenset(
    {
        "tests.test_controle_write_policy",
        "tests.test_controle_write_entrypoints",
    },
)


@pytest.fixture(autouse=True)
def _enable_controle_write_in_integration_tests(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Testes de sync/register assumem escrita habilitada; policy/entrypoints controlam o env."""
    if request.module.__name__ in _WRITE_POLICY_MODULES:
        return
    monkeypatch.setenv(ENV_CONTROLE_WRITE_ENABLED, "true")
