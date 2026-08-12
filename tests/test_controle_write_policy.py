"""Kill switch CONTROLE_WRITE_ENABLED para Controle Assinaturas."""

import pytest

from classificacao_procons.contratos.controle_write_policy import (
    ENV_CONTROLE_WRITE_ENABLED,
    ControleWriteForbiddenError,
    is_controle_write_enabled,
    require_controle_write_enabled,
)
from classificacao_procons.contratos.monday_contracts import create_controle_assinatura_item


class TestControleWritePolicy:
    def test_should_disable_write_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_CONTROLE_WRITE_ENABLED, raising=False)

        assert is_controle_write_enabled() is False

    def test_should_enable_when_env_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_CONTROLE_WRITE_ENABLED, "true")

        assert is_controle_write_enabled() is True

    def test_require_should_raise_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_CONTROLE_WRITE_ENABLED, "false")

        with pytest.raises(ControleWriteForbiddenError):
            require_controle_write_enabled()


class TestControleWriteGuardOnMonday:
    def test_create_controle_should_raise_when_write_disabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(ENV_CONTROLE_WRITE_ENABLED, "false")

        with pytest.raises(ControleWriteForbiddenError):
            create_controle_assinatura_item(
                api_token="token",
                item_name="Test",
                group_id="g1",
                signature_link_text="link",
                status_label="Aguardando Assinatura",
            )
