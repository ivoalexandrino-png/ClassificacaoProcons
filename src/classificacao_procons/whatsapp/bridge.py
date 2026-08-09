"""Integração com WhatsApp via Neonize (sessão do usuário)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from classificacao_procons.whatsapp.history import append_turn, load_state, save_state
from classificacao_procons.whatsapp.models import ChatTurn, IncomingMessage
from classificacao_procons.whatsapp.responder import ResponderOptions, plan_reply

log = logging.getLogger(__name__)


class WhatsappBridgeError(RuntimeError):
    """Erro na ponte com o WhatsApp."""


@dataclass(frozen=True)
class RunOptions:
    session_path: Path
    state_path: Path
    responder: ResponderOptions
    include_groups: bool = False
    dry_run: bool = False


def _chat_id_from_source(source) -> str:
    chat = source.Chat
    user = getattr(chat, "User", "") or ""
    server = getattr(chat, "Server", "") or ""
    return f"{user}@{server}" if user else str(chat)


def _incoming_from_event(event) -> IncomingMessage | None:
    from neonize.utils.message import extract_text

    source = event.Info.MessageSource
    if source.IsFromMe:
        return None

    inner = event.Message
    text = (extract_text(inner) or "").strip()
    if not text:
        return None

    chat_id = _chat_id_from_source(source)
    return IncomingMessage(
        chat_id=chat_id,
        message_id=event.Info.ID,
        text=text,
        contact_label=event.Info.Pushname or None,
        timestamp_ms=event.Info.Timestamp or None,
        is_group=bool(source.IsGroup),
    )


def process_incoming_message(
    incoming: IncomingMessage,
    *,
    options: RunOptions,
    state_loader: Callable[[], object] | None = None,
    state_saver: Callable[[object], None] | None = None,
) -> dict[str, object]:
    """Processa uma mensagem (útil em testes e no listener)."""
    state = load_state(options.state_path) if state_loader is None else state_loader()
    if incoming.message_id in state.processed_message_ids:
        return {"skipped": "already_processed", "message_id": incoming.message_id}

    if incoming.is_group and not options.include_groups:
        return {"skipped": "group_disabled", "message_id": incoming.message_id}

    thread = state.threads.get(incoming.chat_id)
    if thread is None:
        from classificacao_procons.whatsapp.history import get_thread

        thread = get_thread(state, incoming.chat_id)

    append_turn(
        state,
        chat_id=incoming.chat_id,
        turn=ChatTurn(
            role="contact",
            text=incoming.text,
            message_id=incoming.message_id,
            timestamp_ms=incoming.timestamp_ms,
        ),
        contact_label=incoming.contact_label,
    )

    reply_plan = plan_reply(incoming, thread, options=options.responder)

    result: dict[str, object] = {
        "message_id": incoming.message_id,
        "chat_id": incoming.chat_id,
        "tier": reply_plan.tier,
        "reply": reply_plan.reply_text,
        "reasons": list(reply_plan.reasons),
        "dry_run": options.dry_run,
    }

    if not options.dry_run:
        append_turn(
            state,
            chat_id=incoming.chat_id,
            turn=ChatTurn(role="assistant", text=reply_plan.reply_text),
        )

    state.processed_message_ids = frozenset(
        set(state.processed_message_ids) | {incoming.message_id},
    )
    if state_saver is None:
        save_state(options.state_path, state)
    else:
        state_saver(state)

    return result


def run_whatsapp_bot(options: RunOptions) -> None:
    """Conecta ao WhatsApp e responde mensagens automaticamente."""
    try:
        from neonize.client import NewClient
        from neonize.events import ConnectedEv, MessageEv, event
    except ImportError as exc:
        raise WhatsappBridgeError(
            "Instale o extra whatsapp: pip install -e '.[whatsapp]'",
        ) from exc

    pending_replies: list[tuple[object, str]] = []

    def _flush_replies(client: NewClient) -> None:
        while pending_replies:
            quoted, text = pending_replies.pop(0)
            try:
                client.reply_message(text, quoted)
            except Exception as exc:
                log.exception("Falha ao enviar resposta: %s", exc)

    client = NewClient(str(options.session_path))

    @client.event(ConnectedEv)
    def on_connected(_client: NewClient, _event: ConnectedEv) -> None:
        log.info("WhatsApp conectado — modo automático ativo (dry_run=%s)", options.dry_run)

    @client.event(MessageEv)
    def on_message(client: NewClient, message_ev: MessageEv) -> None:
        incoming = _incoming_from_event(message_ev)
        if incoming is None:
            return

        try:
            outcome = process_incoming_message(incoming, options=options)
        except Exception as exc:
            log.exception("Erro ao processar mensagem %s: %s", incoming.message_id, exc)
            return

        if outcome.get("skipped"):
            log.debug("Ignorada: %s", outcome)
            return

        log.info(
            "Respondendo chat=%s tier=%s",
            incoming.chat_id,
            outcome.get("tier"),
        )
        if options.dry_run:
            return

        pending_replies.append((message_ev, str(outcome.get("reply", ""))))
        _flush_replies(client)

    client.connect()
    event.wait()
