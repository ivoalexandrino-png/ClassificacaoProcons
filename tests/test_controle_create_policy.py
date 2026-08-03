"""Testes da política de pausa de criação no Controle Assinaturas."""

import pytest

from classificacao_procons.contratos.controle_create_policy import (
    ENV_PAUSE_CREATE,
    controle_create_paused_message,
    is_controle_create_paused,
)


class TestControleCreatePolicy:
    def test_should_pause_by_default_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_PAUSE_CREATE, raising=False)

        assert is_controle_create_paused() is True

    def test_should_pause_when_env_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_PAUSE_CREATE, "true")

        assert is_controle_create_paused() is True

    def test_should_allow_when_env_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_PAUSE_CREATE, "false")

        assert is_controle_create_paused() is False

    def test_should_override_env_with_allow_create_true(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(ENV_PAUSE_CREATE, "true")

        assert is_controle_create_paused(allow_create=True) is False

    def test_should_force_pause_with_allow_create_false(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(ENV_PAUSE_CREATE, "false")

        assert is_controle_create_paused(allow_create=False) is True

    def test_paused_message_mentions_env(self) -> None:
        assert ENV_PAUSE_CREATE in controle_create_paused_message()
