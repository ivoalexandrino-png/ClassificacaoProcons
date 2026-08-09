"""Testes do notifier de e-mail do Questor."""

import base64
from datetime import date, datetime
from email import message_from_bytes
from unittest.mock import MagicMock

import pytest

from classificacao_procons.questor.analise import analyze_snapshot
from classificacao_procons.questor.models import (
    Certidao,
    QuestorAnalysis,
    QuestorSnapshot,
)
from classificacao_procons.questor.notifier import (
    BuiltEmail,
    GmailSender,
    GmailSenderError,
    build_alert_email,
    build_alert_subject,
)

TODAY = date(2026, 8, 8)


def _analysis_with_issue() -> QuestorAnalysis:
    snapshot = QuestorSnapshot(
        captured_at=datetime(2026, 8, 8, 9, 0),
        empresa="Beauty For All",
        cnpj="12345678000199",
        certidoes=(
            Certidao(orgao="FGTS/CRF", situacao="positiva", url="https://questor/fgts"),
        ),
    )
    return analyze_snapshot(snapshot, today=TODAY)


class TestBuildAlertEmail:
    def test_subject_should_flag_critical_count(self) -> None:
        subject = build_alert_subject(_analysis_with_issue())
        assert "CRÍTICA" in subject
        assert "Beauty For All" in subject

    def test_should_include_issue_details_in_bodies(self) -> None:
        email = build_alert_email(_analysis_with_issue(), to=["fiscal@b4a.com"])
        assert "FGTS/CRF" in email.text_body
        assert "positiva" in email.text_body.lower()
        assert "FGTS/CRF" in email.html_body
        assert "https://questor/fgts" in email.html_body
        assert email.to == ("fiscal@b4a.com",)

    def test_should_carry_cc_recipients(self) -> None:
        email = build_alert_email(
            _analysis_with_issue(),
            to=["fiscal@b4a.com"],
            cc=["contabil@b4a.com"],
        )
        assert email.cc == ("contabil@b4a.com",)

    def test_should_include_details_metadata_and_freshness_note(self) -> None:
        from datetime import date, datetime

        from classificacao_procons.questor.analise import analyze_snapshot
        from classificacao_procons.questor.models import Certidao, QuestorSnapshot

        snapshot = QuestorSnapshot(
            captured_at=datetime(2026, 8, 8, 9, 0),
            empresa="B4A",
            certidoes=(
                Certidao(
                    orgao="Receita Federal/PGFN",
                    situacao="positiva",
                    empresa="B4A SERVICOS",
                    cnpj="13475001000134",
                    uf="SP",
                ),
            ),
        )
        analysis = analyze_snapshot(snapshot, today=date(2026, 8, 8))
        email = build_alert_email(analysis, to=["fiscal@b4a.com"])

        assert "Empresa/Titular: B4A SERVICOS (CNPJ/CPF 13.475.001/0001-34)" in email.text_body
        assert "O que fazer:" in email.text_body
        assert "última captura do Questor" in email.text_body
        assert "13.475.001/0001-34" in email.html_body


class TestGmailSender:
    def test_should_send_multipart_message_with_raw_payload(self) -> None:
        service = MagicMock()
        send = service.users.return_value.messages.return_value.send
        send.return_value.execute.return_value = {"id": "gmail-123"}

        email = build_alert_email(
            _analysis_with_issue(),
            to=["fiscal@b4a.com"],
            cc=["contabil@b4a.com"],
        )
        message_id = GmailSender(service).send(email, sender="agente@b4a.com")

        assert message_id == "gmail-123"
        send.assert_called_once()
        body = send.call_args.kwargs["body"]
        decoded = base64.urlsafe_b64decode(body["raw"].encode("utf-8"))
        parsed = message_from_bytes(decoded)
        assert parsed["To"] == "fiscal@b4a.com"
        assert parsed["Cc"] == "contabil@b4a.com"
        assert parsed["From"] == "agente@b4a.com"
        assert parsed.is_multipart()

    def test_should_raise_when_no_recipients(self) -> None:
        email = BuiltEmail(
            subject="x",
            text_body="x",
            html_body="<p>x</p>",
            to=(),
        )
        with pytest.raises(GmailSenderError, match="destinatário"):
            GmailSender(MagicMock()).send(email)
