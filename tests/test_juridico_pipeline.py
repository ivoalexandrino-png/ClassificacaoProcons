"""Testes do pipeline do agente jurídico."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from classificacao_procons.juridico.models import IntimacaoEmail
from classificacao_procons.juridico.monday_juridico import ProvidenciaRegistrationResult
from classificacao_procons.juridico.pipeline import (
    JuridicoPipelineOptions,
    process_new_intimacoes,
)


def _intimacao(**overrides: object) -> IntimacaoEmail:
    base = {
        "message_id": "msg-1",
        "subject": "Intimação eletrônica",
        "sender": "tribunal@tjsp.jus.br",
        "received_at": datetime(2026, 7, 17, 9, 0),
        "process_number": "1023456-78.2026.8.26.0100",
        "tribunal": "TJSP",
        "vara": "3ª Vara Cível",
        "movement_type": "Citação",
        "prazo_dias": 15,
        "prazo_uteis": True,
        "publication_date": date(2026, 7, 17),
        "body_excerpt": "Citação para contestar",
    }
    base.update(overrides)
    return IntimacaoEmail(**base)  # type: ignore[arg-type]


@patch("classificacao_procons.juridico.pipeline.GmailIntimacaoFetcher")
@patch("classificacao_procons.juridico.pipeline.has_gmail_modify_access", return_value=True)
@patch("classificacao_procons.juridico.pipeline.has_valid_token", return_value=True)
@patch("classificacao_procons.juridico.pipeline.register_providencia")
def test_should_process_intimacao_end_to_end(
    register_mock,
    _token_mock,
    _modify_mock,
    fetcher_cls_mock,
    tmp_path,
) -> None:
    fetcher = MagicMock()
    fetcher_cls_mock.from_credentials.return_value = fetcher
    fetcher.list_unread_intimacoes.return_value = [_intimacao()]
    register_mock.return_value = ProvidenciaRegistrationResult(
        item_id="item-1",
        board_id="board-1",
        item_url="https://b4a.monday.com/boards/board-1/pulses/item-1",
    )

    options = JuridicoPipelineOptions(
        state_path=tmp_path / "state.json",
        monday_api_token="token",
    )
    results = process_new_intimacoes(options)

    assert len(results) == 1
    result = results[0]
    assert result.status == "success"
    assert result.tipo == "Contestar"
    assert result.prazo_final == date(2026, 8, 7)
    assert result.monday_item_url.endswith("item-1")
    assert result.peca_status == "pendente_integracao"
    assert result.relatorio_status == "pendente_integracao"
    fetcher.mark_as_read.assert_called_once_with("msg-1")
    register_mock.assert_called_once()


@patch("classificacao_procons.juridico.pipeline.GmailIntimacaoFetcher")
@patch("classificacao_procons.juridico.pipeline.has_gmail_modify_access", return_value=True)
@patch("classificacao_procons.juridico.pipeline.has_valid_token", return_value=True)
@patch("classificacao_procons.juridico.pipeline.register_providencia")
def test_should_not_register_informative_movement(
    register_mock,
    _token_mock,
    _modify_mock,
    fetcher_cls_mock,
    tmp_path,
) -> None:
    fetcher = MagicMock()
    fetcher_cls_mock.from_credentials.return_value = fetcher
    fetcher.list_unread_intimacoes.return_value = [
        _intimacao(
            movement_type=None,
            prazo_dias=None,
            body_excerpt="Certidão de juntada de documento aos autos.",
        ),
    ]

    options = JuridicoPipelineOptions(
        state_path=tmp_path / "state.json",
        monday_api_token="token",
    )
    results = process_new_intimacoes(options)

    assert results[0].status == "acompanhar"
    assert results[0].relatorio_status == "pendente_integracao"
    assert results[0].peca_status is None
    register_mock.assert_not_called()


@patch("classificacao_procons.juridico.pipeline.GmailIntimacaoFetcher")
@patch("classificacao_procons.juridico.pipeline.has_valid_token", return_value=True)
def test_should_dry_run_without_side_effects(
    _token_mock,
    fetcher_cls_mock,
    tmp_path,
) -> None:
    fetcher = MagicMock()
    fetcher_cls_mock.from_credentials.return_value = fetcher
    fetcher.list_unread_intimacoes.return_value = [_intimacao()]

    options = JuridicoPipelineOptions(
        state_path=tmp_path / "state.json",
        dry_run=True,
    )
    results = process_new_intimacoes(options)

    assert results[0].status == "dry_run"
    assert results[0].prazo_final == date(2026, 8, 7)
    fetcher.mark_as_read.assert_not_called()


@patch("classificacao_procons.juridico.pipeline.GmailIntimacaoFetcher")
@patch("classificacao_procons.juridico.pipeline.has_gmail_modify_access", return_value=True)
@patch("classificacao_procons.juridico.pipeline.has_valid_token", return_value=True)
@patch("classificacao_procons.juridico.pipeline.register_providencia")
def test_should_skip_duplicate_on_second_run(
    register_mock,
    _token_mock,
    _modify_mock,
    fetcher_cls_mock,
    tmp_path,
) -> None:
    fetcher = MagicMock()
    fetcher_cls_mock.from_credentials.return_value = fetcher
    fetcher.list_unread_intimacoes.return_value = [_intimacao()]
    register_mock.return_value = ProvidenciaRegistrationResult(item_id="i", board_id="b")

    options = JuridicoPipelineOptions(
        state_path=tmp_path / "state.json",
        monday_api_token="token",
    )
    first = process_new_intimacoes(options)
    second = process_new_intimacoes(options)

    assert first[0].status == "success"
    assert second[0].status == "skipped_duplicate"


@patch("classificacao_procons.juridico.pipeline.GmailIntimacaoFetcher")
@patch("classificacao_procons.juridico.pipeline.has_gmail_modify_access", return_value=True)
@patch("classificacao_procons.juridico.pipeline.has_valid_token", return_value=True)
@patch("classificacao_procons.juridico.pipeline.register_providencia")
def test_should_capture_monday_error(
    register_mock,
    _token_mock,
    _modify_mock,
    fetcher_cls_mock,
    tmp_path,
) -> None:
    from classificacao_procons.monday.client import MondayClientError

    fetcher = MagicMock()
    fetcher_cls_mock.from_credentials.return_value = fetcher
    fetcher.list_unread_intimacoes.return_value = [_intimacao()]
    register_mock.side_effect = MondayClientError("board não encontrado")

    options = JuridicoPipelineOptions(
        state_path=tmp_path / "state.json",
        monday_api_token="token",
    )
    results = process_new_intimacoes(options)

    assert results[0].monday_error == "board não encontrado"
