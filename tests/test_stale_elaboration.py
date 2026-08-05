"""Testes de seleção de respostas automáticas anteriores ao alinhamento SAC."""

from datetime import UTC, datetime
from unittest.mock import patch

from classificacao_procons.llm.stale_elaboration import (
    is_automatic_response_older_than,
    list_cases_with_stale_automatic_responses,
    parse_utc_cutoff,
)
from classificacao_procons.models import MondayCaseReady


def test_should_parse_utc_cutoff_with_z_suffix() -> None:
    parsed = parse_utc_cutoff("2026-08-05T19:54:00Z")
    assert parsed == datetime(2026, 8, 5, 19, 54, tzinfo=UTC)


@patch("classificacao_procons.llm.stale_elaboration.newest_automatic_response_generated_at")
@patch("classificacao_procons.llm.stale_elaboration.resolve_sac_folder_context")
def test_should_treat_response_as_stale_when_drive_timestamp_before_cutoff(
    resolve_mock,
    newest_mock,
) -> None:
    resolve_mock.return_value = type("Ctx", (), {"consumer_folder_id": "folder-1"})()
    newest_mock.return_value = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    cutoff = datetime(2026, 8, 5, 19, 54, tzinfo=UTC)

    assert is_automatic_response_older_than(
        docs_sac_url="https://drive.google.com/drive/folders/abc",
        before=cutoff,
        token_path="token.json",
    )


@patch("classificacao_procons.llm.stale_elaboration.newest_automatic_response_generated_at")
@patch("classificacao_procons.llm.stale_elaboration.resolve_sac_folder_context")
def test_should_not_treat_response_as_stale_after_sac_cutoff(
    resolve_mock,
    newest_mock,
) -> None:
    resolve_mock.return_value = type("Ctx", (), {"consumer_folder_id": "folder-1"})()
    newest_mock.return_value = datetime(2026, 8, 5, 19, 55, tzinfo=UTC)
    cutoff = datetime(2026, 8, 5, 19, 54, tzinfo=UTC)

    assert not is_automatic_response_older_than(
        docs_sac_url="https://drive.google.com/drive/folders/abc",
        before=cutoff,
        token_path="token.json",
    )


@patch("classificacao_procons.llm.stale_elaboration.is_automatic_response_older_than")
@patch("classificacao_procons.llm.stale_elaboration.list_cases_with_elaborated_responses")
def test_should_limit_stale_cases_to_max_results(
    list_mock,
    is_stale_mock,
) -> None:
    cases = [
        MondayCaseReady(
            item_id=str(index),
            item_name=f"CONSUMER {index}",
            docs_sac_url="https://drive.google.com/drive/folders/abc",
            protocol_number=f"100{index}/2026",
        )
        for index in range(5)
    ]
    list_mock.return_value = cases
    is_stale_mock.side_effect = [True, False, True, True, True]

    stale = list_cases_with_stale_automatic_responses(
        before=datetime(2026, 8, 5, 19, 54, tzinfo=UTC),
        api_token="token",
        token_path="token.json",
        max_cases=2,
    )

    assert len(stale) == 2
    assert stale[0].item_id == "0"
    assert stale[1].item_id == "2"
