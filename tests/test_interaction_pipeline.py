"""Testes do pipeline de interação do consumidor."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from classificacao_procons.interaction_pipeline import (
    ConsumerInteractionPipelineOptions,
    build_interaction_update_body,
    process_consumer_interactions,
)
from classificacao_procons.models import ProconNotificationEmail


def test_build_interaction_update_body_should_include_mentions() -> None:
    body = build_interaction_update_body(
        protocol_number="1623103/2026",
        email_subject="Interação do Consumidor",
        consumer_messages=("Mensagem do consumidor",),
        portal_attachment_labels=(),
        email_attachment_names=("IMG_3492.png",),
        procon_notices=("Convertido em PA",),
    )
    assert "walquiria.marquart@b4a.com.br" in body
    assert "manu@b4a.com.br" in body
    assert "1623103/2026" in body
    assert "IMG_3492.png" in body
    assert "Convertido em PA" in body
    assert "Avisos do órgão" in body


@patch("classificacao_procons.interaction_pipeline.GmailProconFetcher.from_credentials")
@patch("classificacao_procons.interaction_pipeline._post_monday_interaction")
def test_process_consumer_interactions_should_mark_success(
    post_monday_mock,
    fetcher_factory_mock,
    tmp_path: Path,
) -> None:
    post_monday_mock.return_value = "item-123"
    fetcher = MagicMock()
    fetcher.list_unread_consumer_interactions.return_value = [
        ProconNotificationEmail(
            message_id="msg-1",
            subject="Interação do Consumidor",
            sender="procon.naoresponder@procon.sp.gov.br",
            received_at=datetime(2026, 7, 28, tzinfo=UTC),
            portal_url="https://fornecedor2.procon.sp.gov.br",
            source_id="sp",
            access_code="code",
            notification_type="interacao_consumidor",
            protocol_number="1623103/2026",
        ),
    ]
    fetcher.fetch_message_payload.return_value = {"parts": []}
    fetcher_factory_mock.return_value = fetcher

    state_path = tmp_path / "processed-interactions.json"
    options = ConsumerInteractionPipelineOptions(
        state_path=state_path,
        fetch_portal=False,
        monday_api_token="token",
    )

    with patch(
        "classificacao_procons.interaction_pipeline.has_gmail_modify_access",
        return_value=False,
    ):
        results = process_consumer_interactions(options)

    assert len(results) == 1
    assert results[0].status == "success"
    assert results[0].monday_item_id == "item-123"
    post_monday_mock.assert_called_once()


@patch("classificacao_procons.interaction_pipeline.GmailProconFetcher.from_credentials")
@patch("classificacao_procons.interaction_pipeline._post_monday_interaction")
def test_process_consumer_interactions_should_queue_when_monday_missing(
    post_monday_mock,
    fetcher_factory_mock,
    tmp_path: Path,
) -> None:
    from classificacao_procons.monday.client import MondayClientError

    post_monday_mock.side_effect = MondayClientError(
        "Item Monday não encontrado para o protocolo 1623103/2026.",
    )
    fetcher = MagicMock()
    fetcher.list_unread_consumer_interactions.return_value = [
        ProconNotificationEmail(
            message_id="msg-2",
            subject="Interação do Consumidor",
            sender="procon.naoresponder@procon.sp.gov.br",
            received_at=datetime(2026, 7, 28, tzinfo=UTC),
            portal_url="",
            source_id="sp",
            protocol_number="1623103/2026",
            notification_type="interacao_consumidor",
        ),
    ]
    fetcher.fetch_message_payload.return_value = {"parts": []}
    fetcher_factory_mock.return_value = fetcher

    state_path = tmp_path / "processed-interactions.json"
    options = ConsumerInteractionPipelineOptions(
        state_path=state_path,
        fetch_portal=False,
        monday_api_token="token",
    )

    with patch(
        "classificacao_procons.interaction_pipeline.has_gmail_modify_access",
        return_value=False,
    ):
        results = process_consumer_interactions(options)

    assert results[0].status == "pending_monday_item"
    assert state_path.exists()
    payload = state_path.read_text(encoding="utf-8")
    assert "msg-2" in payload
    assert "pending" in payload
