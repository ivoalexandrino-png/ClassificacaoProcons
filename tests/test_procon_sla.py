"""Testes do monitor de SLA Procon."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from classificacao_procons.health.procon_sla import (
    ProconSlaError,
    build_procon_sla_report,
    check_github_workflow_freshness,
)
from classificacao_procons.models import ProconNotificationEmail


def _notification(*, message_id: str, minutes_ago: int) -> ProconNotificationEmail:
    received = datetime.now(tz=UTC).replace(microsecond=0)
    from datetime import timedelta

    received = received - timedelta(minutes=minutes_ago)
    return ProconNotificationEmail(
        message_id=message_id,
        subject="Fundação Procon-SP - Notificação de emissão de CIP",
        sender="procon.naoresponder@procon.sp.gov.br",
        received_at=received,
        portal_url="https://procon.example",
        source_id="sp",
        protocol_number="1720331/2026",
    )


class TestBuildProconSlaReport:
    @patch("classificacao_procons.health.procon_sla.GmailProconFetcher.from_credentials")
    def test_should_flag_unread_older_than_sla(self, fetcher_factory_mock) -> None:
        fetcher = MagicMock()
        fetcher.list_unread_notifications.return_value = [
            _notification(message_id="old", minutes_ago=120),
            _notification(message_id="new", minutes_ago=10),
        ]
        fetcher_factory_mock.return_value = fetcher

        report = build_procon_sla_report(
            token_path="credentials/gmail-token.json",
            max_age_minutes=90,
        )

        assert len(report.stale_notifications) == 1
        assert report.stale_notifications[0].message_id == "old"
        assert report.stale_notifications[0].age_minutes >= 90

    @patch("classificacao_procons.health.procon_sla.GmailProconFetcher.from_credentials")
    def test_should_ignore_consumer_interaction_emails(self, fetcher_factory_mock) -> None:
        fetcher = MagicMock()
        from datetime import timedelta

        received = datetime.now(tz=UTC) - timedelta(minutes=200)
        interaction = ProconNotificationEmail(
            message_id="ix",
            subject="Interação do Consumidor",
            sender="procon.naoresponder@procon.sp.gov.br",
            received_at=received,
            portal_url="https://procon.example",
            notification_type="interacao_consumidor",
        )
        fetcher.list_unread_notifications.return_value = [interaction]
        fetcher_factory_mock.return_value = fetcher

        report = build_procon_sla_report(
            token_path="credentials/gmail-token.json",
            max_age_minutes=90,
        )

        assert report.stale_notifications == ()


class TestCheckGithubWorkflowFreshness:
    def test_should_mark_stale_when_last_run_too_old(self) -> None:
        payload = {
            "workflow_runs": [
                {
                    "created_at": "2020-01-01T12:00:00Z",
                    "status": "completed",
                    "conclusion": "success",
                },
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        response = MagicMock()
        response.read.return_value = body
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=response):
            report = check_github_workflow_freshness(
                token="ghp_test",
                max_age_minutes=60,
                now=datetime(2020, 1, 1, 14, 0, tzinfo=UTC),
            )

        assert report.is_stale is True

    def test_should_raise_when_token_missing(self) -> None:
        with pytest.raises(ProconSlaError, match="Token GitHub"):
            check_github_workflow_freshness(token="", max_age_minutes=60)
