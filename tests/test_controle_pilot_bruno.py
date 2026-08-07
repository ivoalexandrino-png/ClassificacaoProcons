"""Testes da allowlist piloto e comando Bruno."""

from unittest.mock import patch

import pytest

from classificacao_procons.contratos.controle_create_allowlist import (
    controle_may_create_new_item,
    is_controle_pilot_create_allowed,
)
from classificacao_procons.contratos.controle_pilot_bruno import run_bruno_distrato_controle_pilot
from classificacao_procons.contratos.controle_sync import ControleRegistrationResult


class TestControleCreateAllowlist:
    def test_should_allow_bruno_v2_when_pause_enabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CONTROLE_PAUSE_CREATE", "true")
        title = "Distrato Bruno Santos de Castro - 25.06.2026 (2)"
        assert is_controle_pilot_create_allowed(document_name=title) is True
        assert controle_may_create_new_item(document_name=title) is True

    def test_should_not_allow_other_titles_when_pause_enabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CONTROLE_PAUSE_CREATE", "true")
        assert controle_may_create_new_item(document_name="Contrato B2B - X") is False


class TestBrunoPilotCommand:
    @patch("classificacao_procons.contratos.controle_pilot_bruno.register_document_in_controle")
    @patch("classificacao_procons.contratos.controle_pilot_bruno.list_documents")
    @patch("classificacao_procons.contratos.controle_pilot_bruno.get_api_token_from_env")
    def test_should_only_register_v2_title(
        self,
        token_mock,
        list_mock,
        register_mock,
    ) -> None:
        from classificacao_procons.contratos.autentique.client import (
            AutentiqueDocumentSummary,
            AutentiqueSigner,
        )

        token_mock.return_value = "monday"
        list_mock.return_value = [
            AutentiqueDocumentSummary(
                document_id="v2-id",
                name="Distrato Bruno Santos de Castro - 25.06.2026 (2)",
                created_at="2026-08-06",
                signed_pdf_url=None,
                signatures=(),
            ),
            AutentiqueDocumentSummary(
                document_id="v1-id",
                name="Distrato Bruno Santos de Castro - 25.06.2026",
                created_at="2026-06-30",
                signed_pdf_url=None,
                signatures=(
                    AutentiqueSigner(
                        public_id="1",
                        name="x",
                        email=None,
                        short_link=None,
                        signed_at=None,
                    ),
                ),
                deadline_at="2026-08-06T10:00:00+00:00",
            ),
        ]
        register_mock.return_value = ControleRegistrationResult(
            document_id="v2-id",
            document_name="Distrato Bruno Santos de Castro - 25.06.2026 (2)",
            monday_item_id="111",
            monday_item_url=None,
        )

        with patch(
            "classificacao_procons.contratos.controle_pilot_bruno.find_controle_items_by_autentique_id",
            return_value=(),
        ):
            result = run_bruno_distrato_controle_pilot(dry_run=False)

        assert result.v2_document_id == "v2-id"
        assert result.v2_action == "created_v2"
        register_mock.assert_called_once()
