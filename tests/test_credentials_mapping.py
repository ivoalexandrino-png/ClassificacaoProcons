"""Testes de mapeamento de credenciais."""

from classificacao_procons.credentials.mapping import (
    elemento_matches_source,
    normalize_label,
    resolve_field_for_column,
)


class TestCredentialsMapping:
    def test_should_map_login_and_password_columns(self) -> None:
        assert resolve_field_for_column("Login") == "login"
        assert resolve_field_for_column("Senha") == "password"
        assert resolve_field_for_column("Link") == "link"

    def test_should_match_proconsumidor_elemento(self) -> None:
        assert elemento_matches_source("Proconsumidor", "proconsumidor")

    def test_should_match_sao_paulo_aliases(self) -> None:
        assert elemento_matches_source("São Paulo", "sp")
        assert elemento_matches_source("Sao Paulo", "sp")

    def test_should_match_uberlandia_without_accent(self) -> None:
        assert elemento_matches_source("Uberlandia", "uberlandia")

    def test_should_normalize_labels(self) -> None:
        assert normalize_label("  São   Paulo ") == "sao paulo"
