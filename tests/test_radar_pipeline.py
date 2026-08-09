"""Testes do pipeline do radar (snapshot → análise → digest)."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from classificacao_procons.radar.models import Edital, RadarSnapshot
from classificacao_procons.radar.pipeline import (
    RadarPipelineError,
    RadarPipelineOptions,
    run_radar_check,
)


def _snapshot_with_match() -> RadarSnapshot:
    return RadarSnapshot(
        captured_at=datetime(2026, 8, 9, 9, 0),
        editais=(
            Edital(
                source_key="cnpq",
                source_name="CNPq",
                title="Edital de pesquisa em Direito",
                url="https://cnpq.br/edital-1",
                areas=("direito",),
                status="aberto",
            ),
        ),
    )


def _snapshot_without_match() -> RadarSnapshot:
    return RadarSnapshot(
        captured_at=datetime(2026, 8, 9, 9, 0),
        editais=(
            Edital(
                source_key="cnpq",
                source_name="CNPq",
                title="Edital de engenharia aeroespacial",
                url="https://cnpq.br/aero",
                areas=(),
                status="aberto",
            ),
        ),
    )


class TestRunRadarCheck:
    def test_should_report_ok_when_no_matches(self, tmp_path) -> None:
        options = RadarPipelineOptions(
            recipients=("pesquisa@uni.br",),
            state_path=tmp_path / "state.json",
        )
        result = run_radar_check(options, snapshot=_snapshot_without_match())
        assert result.status == "ok"
        assert result.alert_sent is False

    def test_dry_run_should_not_send(self, tmp_path) -> None:
        options = RadarPipelineOptions(
            recipients=("pesquisa@uni.br",),
            dry_run=True,
            state_path=tmp_path / "state.json",
        )
        result = run_radar_check(options, snapshot=_snapshot_with_match())
        assert result.status == "dry_run"
        assert result.alert_sent is False
        assert len(result.new_matches) == 1
        assert not (tmp_path / "state.json").exists()

    @patch("classificacao_procons.radar.pipeline.GmailSender")
    @patch("classificacao_procons.radar.pipeline.has_gmail_send_access", return_value=True)
    def test_should_send_digest_and_persist_state(self, _access, sender_cls, tmp_path) -> None:
        sender = MagicMock()
        sender.send.return_value = "gmail-1"
        sender_cls.from_credentials.return_value = sender
        state_path = tmp_path / "state.json"
        options = RadarPipelineOptions(
            recipients=("pesquisa@uni.br",),
            cc=("prppg@uni.br",),
            state_path=state_path,
        )

        result = run_radar_check(options, snapshot=_snapshot_with_match())

        assert result.status == "alert_sent"
        assert result.message_id == "gmail-1"
        sender.send.assert_called_once()
        assert state_path.exists()

    @patch("classificacao_procons.radar.pipeline.GmailSender")
    @patch("classificacao_procons.radar.pipeline.has_gmail_send_access", return_value=True)
    def test_should_not_resend_already_alerted(self, _access, sender_cls, tmp_path) -> None:
        sender = MagicMock()
        sender.send.return_value = "gmail-1"
        sender_cls.from_credentials.return_value = sender
        options = RadarPipelineOptions(
            recipients=("pesquisa@uni.br",),
            state_path=tmp_path / "state.json",
        )

        first = run_radar_check(options, snapshot=_snapshot_with_match())
        assert first.status == "alert_sent"

        second = run_radar_check(options, snapshot=_snapshot_with_match())
        assert second.status == "no_new_matches"
        assert sender.send.call_count == 1

    def test_should_raise_when_no_recipients(self, tmp_path) -> None:
        options = RadarPipelineOptions(state_path=tmp_path / "state.json")
        with pytest.raises(RadarPipelineError, match="destinatário"):
            run_radar_check(options, snapshot=_snapshot_with_match())

    @patch("classificacao_procons.radar.pipeline.has_gmail_send_access", return_value=False)
    def test_should_raise_when_token_lacks_send_scope(self, _access, tmp_path) -> None:
        options = RadarPipelineOptions(
            recipients=("pesquisa@uni.br",),
            state_path=tmp_path / "state.json",
        )
        with pytest.raises(RadarPipelineError, match="permissão de envio"):
            run_radar_check(options, snapshot=_snapshot_with_match())

    def test_should_use_injected_snapshot_provider(self, tmp_path) -> None:
        options = RadarPipelineOptions(
            recipients=("pesquisa@uni.br",),
            dry_run=True,
            state_path=tmp_path / "state.json",
        )
        provider = MagicMock(return_value=_snapshot_with_match())
        result = run_radar_check(options, snapshot_provider=provider)
        assert result.status == "dry_run"
        provider.assert_called_once_with(options)
