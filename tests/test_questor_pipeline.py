"""Testes do pipeline do Questor (snapshot → análise → alerta)."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from classificacao_procons.questor.models import (
    Certidao,
    MensagemCaixaPostal,
    QuestorSnapshot,
)
from classificacao_procons.questor.pipeline import (
    QuestorPipelineError,
    QuestorPipelineOptions,
    run_questor_check,
)

TODAY = date(2026, 8, 8)


def _snapshot_with_problem() -> QuestorSnapshot:
    return QuestorSnapshot(
        captured_at=datetime(2026, 8, 8, 9, 0),
        empresa="Beauty For All",
        cnpj="12345678000199",
        certidoes=(Certidao(orgao="FGTS/CRF", situacao="positiva"),),
    )


def _clean_snapshot() -> QuestorSnapshot:
    return QuestorSnapshot(
        captured_at=datetime(2026, 8, 8, 9, 0),
        certidoes=(Certidao(orgao="FGTS/CRF", data_validade=date(2026, 12, 31)),),
        mensagens=(MensagemCaixaPostal(orgao="e-CAC", assunto="Ok", lida=True),),
    )


class TestRunQuestorCheck:
    def test_should_report_ok_when_no_problems(self, tmp_path) -> None:
        options = QuestorPipelineOptions(
            recipients=("fiscal@b4a.com",),
            state_path=tmp_path / "state.json",
        )
        result = run_questor_check(options, snapshot=_clean_snapshot(), today=TODAY)
        assert result.status == "ok"
        assert result.alert_sent is False

    def test_dry_run_should_not_send_email(self, tmp_path) -> None:
        options = QuestorPipelineOptions(
            recipients=("fiscal@b4a.com",),
            dry_run=True,
            state_path=tmp_path / "state.json",
        )
        result = run_questor_check(options, snapshot=_snapshot_with_problem(), today=TODAY)
        assert result.status == "dry_run"
        assert result.alert_sent is False
        assert len(result.new_issues) == 1
        assert not (tmp_path / "state.json").exists()

    @patch("classificacao_procons.questor.pipeline.GmailSender")
    @patch(
        "classificacao_procons.questor.pipeline.has_gmail_send_access",
        return_value=True,
    )
    def test_should_send_alert_and_persist_state(
        self,
        _send_access,
        sender_cls,
        tmp_path,
    ) -> None:
        sender = MagicMock()
        sender.send.return_value = "gmail-1"
        sender_cls.from_credentials.return_value = sender
        state_path = tmp_path / "state.json"
        options = QuestorPipelineOptions(
            recipients=("fiscal@b4a.com",),
            cc=("contabil@b4a.com",),
            state_path=state_path,
        )

        result = run_questor_check(options, snapshot=_snapshot_with_problem(), today=TODAY)

        assert result.status == "alert_sent"
        assert result.alert_sent is True
        assert result.message_id == "gmail-1"
        sender.send.assert_called_once()
        assert state_path.exists()

    @patch("classificacao_procons.questor.pipeline.GmailSender")
    @patch(
        "classificacao_procons.questor.pipeline.has_gmail_send_access",
        return_value=True,
    )
    def test_should_not_resend_already_alerted_issue(
        self,
        _send_access,
        sender_cls,
        tmp_path,
    ) -> None:
        sender = MagicMock()
        sender.send.return_value = "gmail-1"
        sender_cls.from_credentials.return_value = sender
        state_path = tmp_path / "state.json"
        options = QuestorPipelineOptions(
            recipients=("fiscal@b4a.com",),
            state_path=state_path,
        )

        first = run_questor_check(options, snapshot=_snapshot_with_problem(), today=TODAY)
        assert first.status == "alert_sent"

        second = run_questor_check(options, snapshot=_snapshot_with_problem(), today=TODAY)
        assert second.status == "no_new_issues"
        assert sender.send.call_count == 1

    @patch("classificacao_procons.questor.pipeline.GmailSender")
    @patch(
        "classificacao_procons.questor.pipeline.has_gmail_send_access",
        return_value=True,
    )
    def test_weekly_digest_resends_already_alerted(
        self,
        _send_access,
        sender_cls,
        tmp_path,
    ) -> None:
        sender = MagicMock()
        sender.send.return_value = "gmail-1"
        sender_cls.from_credentials.return_value = sender
        state_path = tmp_path / "state.json"
        base = QuestorPipelineOptions(
            recipients=("fiscal@b4a.com",),
            state_path=state_path,
        )
        first = run_questor_check(base, snapshot=_snapshot_with_problem(), today=TODAY)
        assert first.status == "alert_sent"

        # Dia comum: nada novo → não envia.
        again = run_questor_check(base, snapshot=_snapshot_with_problem(), today=TODAY)
        assert again.status == "no_new_issues"

        # Resumo semanal: reenvia mesmo já alertado, com weekly=True.
        weekly = QuestorPipelineOptions(
            recipients=("fiscal@b4a.com",),
            state_path=state_path,
            weekly_digest=True,
        )
        result = run_questor_check(weekly, snapshot=_snapshot_with_problem(), today=TODAY)
        assert result.status == "alert_sent"
        assert len(result.new_issues) == 1
        assert sender.send.call_count == 2

    @patch("classificacao_procons.questor.pipeline.GmailSender")
    @patch(
        "classificacao_procons.questor.pipeline.has_gmail_send_access",
        return_value=True,
    )
    def test_weekly_sends_all_clear_when_no_problems(
        self,
        _send_access,
        sender_cls,
        tmp_path,
    ) -> None:
        sender = MagicMock()
        sender.send.return_value = "gmail-ok"
        sender_cls.from_credentials.return_value = sender
        options = QuestorPipelineOptions(
            recipients=("fiscal@b4a.com",),
            state_path=tmp_path / "state.json",
            weekly_digest=True,
        )
        result = run_questor_check(options, snapshot=_clean_snapshot(), today=TODAY)
        assert result.status == "weekly_ok_sent"
        assert result.alert_sent is True
        sender.send.assert_called_once()

    def test_daily_stays_silent_when_no_problems(self, tmp_path) -> None:
        options = QuestorPipelineOptions(
            recipients=("fiscal@b4a.com",),
            state_path=tmp_path / "state.json",
        )
        result = run_questor_check(options, snapshot=_clean_snapshot(), today=TODAY)
        assert result.status == "ok"
        assert result.alert_sent is False

    def test_should_raise_when_no_recipients(self, tmp_path) -> None:
        options = QuestorPipelineOptions(state_path=tmp_path / "state.json")
        with pytest.raises(QuestorPipelineError, match="destinatário"):
            run_questor_check(options, snapshot=_snapshot_with_problem(), today=TODAY)

    @patch(
        "classificacao_procons.questor.pipeline.has_gmail_send_access",
        return_value=False,
    )
    def test_should_raise_when_token_lacks_send_scope(self, _send_access, tmp_path) -> None:
        options = QuestorPipelineOptions(
            recipients=("fiscal@b4a.com",),
            state_path=tmp_path / "state.json",
        )
        with pytest.raises(QuestorPipelineError, match="permissão de envio"):
            run_questor_check(options, snapshot=_snapshot_with_problem(), today=TODAY)

    def test_should_use_injected_snapshot_provider(self, tmp_path) -> None:
        options = QuestorPipelineOptions(
            recipients=("fiscal@b4a.com",),
            dry_run=True,
            state_path=tmp_path / "state.json",
        )
        provider = MagicMock(return_value=_snapshot_with_problem())
        result = run_questor_check(options, snapshot_provider=provider, today=TODAY)
        assert result.status == "dry_run"
        provider.assert_called_once_with(options)
