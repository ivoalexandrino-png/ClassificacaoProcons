"""Testes de histórico e deduplicação WhatsApp."""

from pathlib import Path

from classificacao_procons.whatsapp.history import append_turn, load_state, save_state
from classificacao_procons.whatsapp.models import BotState, ChatTurn


def test_should_persist_threads_and_processed_ids(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = BotState()
    append_turn(
        state,
        chat_id="chat-1",
        turn=ChatTurn(role="contact", text="Oi", message_id="a"),
        contact_label="Maria",
    )
    state.processed_message_ids = frozenset({"a"})
    save_state(path, state)

    loaded = load_state(path)
    assert "a" in loaded.processed_message_ids
    assert loaded.threads["chat-1"].contact_label == "Maria"
    assert loaded.threads["chat-1"].turns[0].text == "Oi"
