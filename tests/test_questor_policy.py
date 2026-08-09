"""Testes da política de seleção de mensagens da caixa postal."""

from datetime import date

import pytest

from classificacao_procons.questor.models import MensagemCaixaPostal
from classificacao_procons.questor.policy import select_actionable_messages, unread_summary

TODAY = date(2026, 8, 8)


def _msg(**kwargs) -> MensagemCaixaPostal:
    base = {"orgao": "São Paulo", "assunto": "EFD", "lida": False}
    base.update(kwargs)
    return MensagemCaixaPostal(**base)


MSGS = [
    _msg(assunto="rotineira", lida=False, relevante=False),
    _msg(assunto="relevante", lida=False, relevante=True),
    _msg(assunto="com prazo", lida=False, prazo_ciencia=date(2026, 8, 20)),
    _msg(assunto="recente", lida=False, data_postagem=date(2026, 8, 6)),
    _msg(assunto="lida", lida=True, relevante=True),
]


def test_mode_todas_returns_all_unread() -> None:
    assert len(select_actionable_messages(MSGS, mode="todas", today=TODAY)) == 4


def test_mode_relevantes_returns_only_relevant_unread() -> None:
    result = select_actionable_messages(MSGS, mode="relevantes", today=TODAY)
    assert [m.assunto for m in result] == ["relevante"]


def test_explicit_relevante_ou_prazo_mode() -> None:
    result = select_actionable_messages(MSGS, mode="relevante_ou_prazo", today=TODAY)
    assert sorted(m.assunto for m in result) == ["com prazo", "relevante"]


def test_default_mode_selects_by_subject() -> None:
    msgs = [
        _msg(assunto="Escrituração Fiscal Digital", lida=False),  # rotineira → fora
        _msg(assunto="Auto de Infração nº 1", lida=False),  # relevante → dentro
        _msg(assunto="Vencimento de Certidão Conjunta", lida=False),  # relevante → dentro
        _msg(assunto="Auto de Infração antigo", lida=True),  # lida → fora
    ]
    result = select_actionable_messages(msgs, today=TODAY)
    assert sorted(m.assunto for m in result) == [
        "Auto de Infração nº 1",
        "Vencimento de Certidão Conjunta",
    ]


def test_mode_recentes_includes_window() -> None:
    result = select_actionable_messages(MSGS, mode="recentes", window_days=15, today=TODAY)
    assert sorted(m.assunto for m in result) == ["com prazo", "recente", "relevante"]


def test_invalid_mode_raises() -> None:
    with pytest.raises(ValueError, match="inválido"):
        select_actionable_messages(MSGS, mode="xpto", today=TODAY)


def test_unread_summary_counts_by_domicilio() -> None:
    msgs = [
        _msg(orgao="São Paulo", lida=False),
        _msg(orgao="São Paulo", lida=False),
        _msg(orgao="e-CAC", lida=False),
        _msg(orgao="e-CAC", lida=True),
    ]
    summary = unread_summary(msgs)
    assert "3 mensagem" in summary
    assert "São Paulo: 2" in summary
    assert "e-CAC: 1" in summary


def test_unread_summary_none_when_all_read() -> None:
    assert unread_summary([_msg(lida=True)]) is None
