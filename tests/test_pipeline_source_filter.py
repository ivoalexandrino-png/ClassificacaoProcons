"""Testes do filtro de fontes no pipeline."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from classificacao_procons.models import ProconNotificationEmail
from classificacao_procons.pipeline import PipelineOptions, process_new_complaints


def _notification(*, source_id: str, protocol: str) -> ProconNotificationEmail:
    return ProconNotificationEmail(
        message_id=f"msg-{source_id}",
        subject="Notificação",
        sender="test@example.com",
        received_at=datetime(2026, 7, 23, 13, 24),
        portal_url="https://example.com",
        source_id=source_id,
        protocol_number=protocol,
    )


@patch("classificacao_procons.pipeline.GmailProconFetcher")
@patch("classificacao_procons.pipeline.has_valid_token", return_value=True)
@patch("classificacao_procons.pipeline._process_notification")
def test_should_filter_notifications_by_source_ids(
    process_mock,
    _has_token_mock,
    fetcher_cls_mock,
) -> None:
    fetcher = MagicMock()
    fetcher_cls_mock.from_credentials.return_value = fetcher
    fetcher.list_unread_notifications.return_value = [
        _notification(source_id="proconsumidor", protocol="26.07.0158.011.00300-301"),
        _notification(source_id="sp", protocol="123"),
    ]

    process_new_complaints(
        PipelineOptions(
            source_ids=("proconsumidor",),
            dry_run=True,
        ),
    )

    assert process_mock.call_count == 1
    assert process_mock.call_args.args[0].source_id == "proconsumidor"
