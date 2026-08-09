"""Testes do classificador de risco WhatsApp."""

from classificacao_procons.whatsapp.risk import heuristic_risk_tier


def test_should_flag_legal_high_when_procon_mentioned() -> None:
    assert heuristic_risk_tier("Recebi notificação do Procon, o que faço?") == "legal_high"


def test_should_flag_legal_high_when_contract_mentioned() -> None:
    assert heuristic_risk_tier("Pode assinar esse contrato hoje?") == "legal_high"


def test_should_flag_ambiguous_when_uncertain_phrasing() -> None:
    tier = heuristic_risk_tier("Acho que talvez não tenho certeza?")
    assert tier == "ambiguous"


def test_should_return_none_for_routine_greeting() -> None:
    assert heuristic_risk_tier("Oi, tudo bem? Nos vemos amanhã?") is None
