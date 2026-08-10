"""Testes da resolução de backend (Monday por padrão; Sunday na migração)."""

import pytest

from classificacao_procons.monday.backend import (
    BACKEND_MONDAY,
    BACKEND_SUNDAY,
    BackendConfigError,
    get_api_token,
    get_backend_config,
    get_backend_name,
)

_BACKEND_ENV_VARS = (
    "LEGAL_BACKEND",
    "LEGAL_API_URL",
    "LEGAL_FILE_API_URL",
    "LEGAL_API_VERSION",
    "LEGAL_API_TOKEN",
    "MONDAY_API_TOKEN",
    "SUNDAY_API_URL",
    "SUNDAY_FILE_API_URL",
    "SUNDAY_API_VERSION",
    "SUNDAY_API_TOKEN",
)


@pytest.fixture(autouse=True)
def _clean_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _BACKEND_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


class TestBackendName:
    def test_should_default_to_monday_when_unset(self) -> None:
        assert get_backend_name() == BACKEND_MONDAY

    def test_should_be_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LEGAL_BACKEND", "Sunday")
        assert get_backend_name() == BACKEND_SUNDAY


class TestMondayBackend:
    def test_should_use_monday_defaults(self) -> None:
        config = get_backend_config()
        assert config.name == BACKEND_MONDAY
        assert config.api_url == "https://api.monday.com/v2"
        assert config.file_api_url == "https://api.monday.com/v2/file"
        assert config.api_version == "2024-10"
        assert config.token_env == "MONDAY_API_TOKEN"

    def test_should_honor_generic_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LEGAL_API_URL", "https://example.test/api")
        monkeypatch.setenv("LEGAL_API_VERSION", "2025-01")
        config = get_backend_config()
        assert config.api_url == "https://example.test/api"
        assert config.api_version == "2025-01"

    def test_should_read_monday_token_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MONDAY_API_TOKEN", "monday-secret")
        assert get_api_token() == "monday-secret"

    def test_should_return_none_when_no_token(self) -> None:
        assert get_api_token() is None


class TestSundayBackend:
    def test_should_require_endpoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LEGAL_BACKEND", "sunday")
        with pytest.raises(BackendConfigError, match="SUNDAY_API_URL"):
            get_backend_config()

    def test_should_resolve_from_sunday_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LEGAL_BACKEND", "sunday")
        monkeypatch.setenv("SUNDAY_API_URL", "https://sunday.b4a.ai/api/v2")
        config = get_backend_config()
        assert config.name == BACKEND_SUNDAY
        assert config.api_url == "https://sunday.b4a.ai/api/v2"
        assert config.file_api_url == "https://sunday.b4a.ai/api/v2/file"
        assert config.api_version is None
        assert config.token_env == "SUNDAY_API_TOKEN"

    def test_should_prefer_sunday_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LEGAL_BACKEND", "sunday")
        monkeypatch.setenv("SUNDAY_API_URL", "https://sunday.b4a.ai/api/v2")
        monkeypatch.setenv("SUNDAY_API_TOKEN", "sunday-secret")
        monkeypatch.setenv("MONDAY_API_TOKEN", "monday-secret")
        assert get_api_token() == "sunday-secret"

    def test_should_fall_back_to_monday_token_at_cutover(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LEGAL_BACKEND", "sunday")
        monkeypatch.setenv("SUNDAY_API_URL", "https://sunday.b4a.ai/api/v2")
        monkeypatch.setenv("MONDAY_API_TOKEN", "shared-secret")
        assert get_api_token() == "shared-secret"


class TestInvalidBackend:
    def test_should_raise_for_unknown_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LEGAL_BACKEND", "trello")
        with pytest.raises(BackendConfigError, match="LEGAL_BACKEND inválido"):
            get_backend_config()
