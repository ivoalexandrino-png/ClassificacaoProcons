"""Persistência de histórico e deduplicação."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from classificacao_procons.whatsapp.models import BotState, ChatTurn, ConversationThread

DEFAULT_MAX_TURNS_PER_CHAT = 40


class HistoryStoreError(RuntimeError):
    """Erro ao ler/gravar histórico."""


def _turn_from_dict(data: dict[str, Any]) -> ChatTurn:
    return ChatTurn(
        role=data["role"],
        text=str(data.get("text", "")),
        message_id=data.get("message_id"),
        timestamp_ms=data.get("timestamp_ms"),
    )


def _thread_from_dict(data: dict[str, Any]) -> ConversationThread:
    turns = [_turn_from_dict(item) for item in data.get("turns", [])]
    return ConversationThread(
        chat_id=str(data["chat_id"]),
        contact_label=data.get("contact_label"),
        turns=turns,
    )


def load_state(path: Path) -> BotState:
    if not path.exists():
        return BotState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoryStoreError(f"Não foi possível ler {path}: {exc}") from exc

    processed = frozenset(str(item) for item in raw.get("processed_message_ids", []))
    threads: dict[str, ConversationThread] = {}
    for chat_id, thread_data in raw.get("threads", {}).items():
        threads[str(chat_id)] = _thread_from_dict(thread_data)
    return BotState(processed_message_ids=processed, threads=threads)


def save_state(path: Path, state: BotState) -> None:
    payload = {
        "processed_message_ids": sorted(state.processed_message_ids),
        "threads": {
            chat_id: {
                "chat_id": thread.chat_id,
                "contact_label": thread.contact_label,
                "turns": [asdict(turn) for turn in thread.turns],
            }
            for chat_id, thread in state.threads.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_thread(state: BotState, chat_id: str) -> ConversationThread:
    existing = state.threads.get(chat_id)
    if existing is not None:
        return existing
    thread = ConversationThread(chat_id=chat_id)
    state.threads[chat_id] = thread
    return thread


def append_turn(
    state: BotState,
    *,
    chat_id: str,
    turn: ChatTurn,
    contact_label: str | None = None,
    max_turns: int = DEFAULT_MAX_TURNS_PER_CHAT,
) -> None:
    thread = get_thread(state, chat_id)
    if contact_label and not thread.contact_label:
        thread.contact_label = contact_label
    thread.turns.append(turn)
    if len(thread.turns) > max_turns:
        thread.turns = thread.turns[-max_turns:]


def format_history_for_prompt(thread: ConversationThread, *, max_chars: int = 6000) -> str:
    lines: list[str] = []
    for turn in thread.turns:
        label = {"contact": "Contato", "owner": "Eu", "assistant": "Assistente"}.get(
            turn.role,
            turn.role,
        )
        lines.append(f"{label}: {turn.text.strip()}")
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]
