"""Testes do planejador de respostas WhatsApp."""

from unittest.mock import patch

from classificacao_procons.whatsapp.llm import LlmReplyResult
from classificacao_procons.whatsapp.models import ChatTurn, ConversationThread, IncomingMessage
from classificacao_procons.whatsapp.responder import plan_reply


def test_should_use_legal_hold_without_llm_when_heuristic_legal() -> None:
    incoming = IncomingMessage(
        chat_id="5511999999999@s.whatsapp.net",
        message_id="m1",
        text="Temos uma intimação judicial para responder",
        contact_label="Ana",
        timestamp_ms=1,
        is_group=False,
    )
    plan = plan_reply(incoming, ConversationThread(chat_id=incoming.chat_id))
    assert plan.tier == "legal_high"
    assert "cautela" in plan.reply_text.lower()
    assert "heurística jurídica" in plan.reasons


@patch("classificacao_procons.whatsapp.responder.generate_whatsapp_reply")
def test_should_force_legal_hold_when_llm_marks_legal(mock_llm) -> None:
    mock_llm.return_value = LlmReplyResult(
        tier="legal_high",
        reply_text="Pode assinar sim, sem problemas.",
        reasons=("llm",),
    )
    incoming = IncomingMessage(
        chat_id="5511888888888@s.whatsapp.net",
        message_id="m2",
        text="Me manda o endereço?",
        contact_label="Bob",
        timestamp_ms=2,
        is_group=False,
    )
    plan = plan_reply(incoming, ConversationThread(chat_id=incoming.chat_id))
    assert plan.tier == "legal_high"
    assert "assinar" not in plan.reply_text.lower()


@patch("classificacao_procons.whatsapp.responder.generate_whatsapp_reply")
def test_should_use_history_context_in_prompt_path(mock_llm) -> None:
    mock_llm.return_value = LlmReplyResult(
        tier="routine",
        reply_text="Perfeito, confirmado às 15h.",
        reasons=(),
    )
    thread = ConversationThread(chat_id="c1")
    thread.turns.append(ChatTurn(role="contact", text="Podemos às 15h?"))
    incoming = IncomingMessage(
        chat_id="c1",
        message_id="m3",
        text="Combinado então",
        contact_label="Carla",
        timestamp_ms=3,
        is_group=False,
    )
    plan = plan_reply(incoming, thread)
    assert plan.reply_text == "Perfeito, confirmado às 15h."
    assert plan.used_history is True
    mock_llm.assert_called_once()
