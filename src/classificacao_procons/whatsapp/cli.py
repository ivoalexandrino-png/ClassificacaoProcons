"""CLI do agente WhatsApp."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from classificacao_procons.whatsapp.bridge import (
    RunOptions,
    WhatsappBridgeError,
    process_incoming_message,
    run_whatsapp_bot,
)
from classificacao_procons.whatsapp.history import get_thread, load_state
from classificacao_procons.whatsapp.models import IncomingMessage
from classificacao_procons.whatsapp.responder import DEFAULT_PERSONA, ResponderOptions, plan_reply


def _default_session_path() -> Path:
    return Path(os.environ.get("WHATSAPP_SESSION_PATH", "data/whatsapp-session.sqlite3"))


def _default_state_path() -> Path:
    return Path(os.environ.get("WHATSAPP_STATE_PATH", "data/whatsapp-bot-state.json"))


def _responder_from_env() -> ResponderOptions:
    persona = os.environ.get("WHATSAPP_PERSONA", "").strip()
    owner = os.environ.get("WHATSAPP_OWNER_NAME", "").strip() or "eu"
    return ResponderOptions(
        owner_name=owner,
        persona=persona or DEFAULT_PERSONA,
    )


def _run_preview(args: argparse.Namespace) -> int:
    state = load_state(Path(args.state_path))
    thread = get_thread(state, args.chat_id)
    if args.contact:
        thread.contact_label = args.contact

    incoming = IncomingMessage(
        chat_id=args.chat_id,
        message_id=args.message_id or "preview-1",
        text=args.text,
        contact_label=args.contact or thread.contact_label,
        timestamp_ms=None,
        is_group=args.group,
    )
    plan = plan_reply(incoming, thread, options=_responder_from_env())
    print(
        json.dumps(
            {
                "tier": plan.tier,
                "reply": plan.reply_text,
                "reasons": list(plan.reasons),
                "used_history": plan.used_history,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return 0


def _run_simulate(args: argparse.Namespace) -> int:
    options = RunOptions(
        session_path=_default_session_path(),
        state_path=Path(args.state_path),
        responder=_responder_from_env(),
        include_groups=args.include_groups,
        dry_run=True,
    )
    incoming = IncomingMessage(
        chat_id=args.chat_id,
        message_id=args.message_id,
        text=args.text,
        contact_label=args.contact,
        timestamp_ms=None,
        is_group=args.group,
    )
    outcome = process_incoming_message(incoming, options=options)
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    return 0


def _run_daemon(args: argparse.Namespace) -> int:
    options = RunOptions(
        session_path=Path(args.session_path),
        state_path=Path(args.state_path),
        responder=_responder_from_env(),
        include_groups=args.include_groups,
        dry_run=args.dry_run,
    )
    try:
        run_whatsapp_bot(options)
    except WhatsappBridgeError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="whatsapp",
        description="Respostas automáticas no WhatsApp com IA e filtro de risco jurídico.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    preview = sub.add_parser("preview", help="Gera resposta offline (sem enviar)")
    preview.add_argument(
        "--chat-id",
        required=True,
        help="ID do chat (ex.: 5511999999999@s.whatsapp.net)",
    )
    preview.add_argument("--text", required=True, help="Texto recebido")
    preview.add_argument("--contact", help="Nome exibido do contato")
    preview.add_argument("--group", action="store_true", help="Simular mensagem em grupo")
    preview.add_argument("--state-path", default=str(_default_state_path()))
    preview.add_argument("--message-id", help="ID opcional da mensagem")
    preview.set_defaults(func=_run_preview)

    simulate = sub.add_parser("simulate", help="Processa mensagem e grava histórico (dry-run)")
    simulate.add_argument("--chat-id", required=True)
    simulate.add_argument("--text", required=True)
    simulate.add_argument("--message-id", default="simulate-1")
    simulate.add_argument("--contact")
    simulate.add_argument("--group", action="store_true")
    simulate.add_argument("--include-groups", action="store_true")
    simulate.add_argument("--state-path", default=str(_default_state_path()))
    simulate.set_defaults(func=_run_simulate)

    run = sub.add_parser("run", help="Conecta ao WhatsApp e responde automaticamente")
    run.add_argument("--session-path", default=str(_default_session_path()))
    run.add_argument("--state-path", default=str(_default_state_path()))
    run.add_argument("--include-groups", action="store_true", help="Responder também em grupos")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Não envia mensagens; apenas registra no log",
    )
    run.set_defaults(func=_run_daemon)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
