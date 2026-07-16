"""CLI e servidor HTTP para webhooks de contratos."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from classificacao_procons.contratos.autentique.webhook import (
    AutentiqueWebhookError,
    parse_webhook_event,
    verify_webhook_signature,
)
from classificacao_procons.contratos.contratos_enrichment import (
    ContratosEnrichmentError,
    process_contratos_item_created,
)
from classificacao_procons.contratos.controle_sync import (
    ControleSyncError,
    process_document_created_webhook_event,
    register_document_in_controle,
    sync_controle_from_autentique,
)
from classificacao_procons.contratos.monday_webhook import (
    MondayWebhookError,
    build_challenge_response,
    is_contratos_item_created_event,
    parse_monday_webhook,
)
from classificacao_procons.contratos.pipeline import (
    ContractPipelineError,
    ContractPipelineOptions,
    process_finished_document,
    process_finished_webhook_event,
)

ENV_WEBHOOK_SECRET = "AUTENTIQUE_WEBHOOK_SECRET"
DEFAULT_PORT = 8080


def _run_register_controle(args: argparse.Namespace) -> int:
    try:
        result = register_document_in_controle(
            document_id=args.document_id,
            monday_api_token=None,
            autentique_api_token=None,
        )
    except ControleSyncError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0


def _dispatch_autentique_event(
    event,
    *,
    options: ContractPipelineOptions,
) -> None:
    if event.event_type == "document.created":
        process_document_created_webhook_event(
            event,
            monday_api_token=options.monday_api_token,
            autentique_api_token=options.autentique_api_token,
        )
        return
    if event.event_type == "document.finished":
        process_finished_webhook_event(event, options=options)
        return


def _run_sync_controle(args: argparse.Namespace) -> int:
    try:
        result = sync_controle_from_autentique(dry_run=args.dry_run, max_pages=args.max_pages)
    except ControleSyncError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    summary = {
        "total_autentique": result.total_autentique,
        "already_in_monday": result.already_in_monday,
        "created": result.created,
        "skipped": result.skipped,
        "failed": result.failed,
        "dry_run": result.dry_run,
        "items": [item.__dict__ for item in result.items if item.action != "already_exists"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result.failed == 0 else 1


def _run_process_document(args: argparse.Namespace) -> int:
    options = ContractPipelineOptions(
        dry_run=args.dry_run,
        skip_gemini=args.skip_gemini,
        token_path=args.token,
    )
    try:
        result = process_finished_document(
            document_id=args.document_id,
            options=options,
        )
    except ContractPipelineError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0


def _make_handler(*, options: ContractPipelineOptions, webhook_secret: str | None):
    class WebhookHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_POST(self) -> None:
            if self.path not in ("/webhooks/autentique", "/"):
                self.send_response(404)
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", "0") or "0")
            raw_body = self.rfile.read(length)

            if webhook_secret:
                signature = self.headers.get("X-Autentique-Signature")
                if not verify_webhook_signature(
                    raw_body=raw_body,
                    signature_header=signature,
                    secret=webhook_secret,
                ):
                    self.send_response(401)
                    self.end_headers()
                    return

            try:
                event = parse_webhook_event(raw_body)
            except AutentiqueWebhookError as exc:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(exc).encode("utf-8"))
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"received":true}')

            if event.event_type not in ("document.created", "document.finished"):
                return

            def _process() -> None:
                from classificacao_procons.monday.client import get_api_token_from_env

                opts = ContractPipelineOptions(
                    token_path=options.token_path,
                    skip_gemini=options.skip_gemini,
                    monday_api_token=options.monday_api_token or get_api_token_from_env(),
                    autentique_api_token=options.autentique_api_token,
                )
                try:
                    _dispatch_autentique_event(event, options=opts)
                except (ContractPipelineError, ControleSyncError):
                    return

            threading.Thread(target=_process, daemon=True).start()

    return WebhookHandler


def _make_monday_handler(*, options: ContractPipelineOptions):
    class MondayWebhookHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_POST(self) -> None:
            if self.path not in ("/webhooks/monday", "/"):
                self.send_response(404)
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", "0") or "0")
            raw_body = self.rfile.read(length)

            try:
                event = parse_monday_webhook(raw_body)
            except MondayWebhookError as exc:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(exc).encode("utf-8"))
                return

            if event.event_type == "challenge":
                response = build_challenge_response(event)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode("utf-8"))
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"received":true}')

            if not is_contratos_item_created_event(event):
                return

            def _process() -> None:
                from classificacao_procons.monday.client import get_api_token_from_env

                token = options.monday_api_token or get_api_token_from_env()
                if not token:
                    return
                try:
                    process_contratos_item_created(
                        event,
                        api_token=token,
                        gemini_api_key=options.gemini_api_key,
                        skip_gemini=options.skip_gemini,
                    )
                except ContratosEnrichmentError:
                    return

            threading.Thread(target=_process, daemon=True).start()

    return MondayWebhookHandler


def _run_serve_monday(args: argparse.Namespace) -> int:
    options = ContractPipelineOptions(
        skip_gemini=args.skip_gemini,
        monday_api_token=None,
        gemini_api_key=None,
    )
    handler = _make_monday_handler(options=options)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Webhook Monday escutando em http://{args.host}:{args.port}/webhooks/monday")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando servidor.")
        return 0


def _run_serve(args: argparse.Namespace) -> int:
    webhook_secret = os.environ.get(ENV_WEBHOOK_SECRET, "").strip() or None
    options = ContractPipelineOptions(
        token_path=args.token,
        skip_gemini=args.skip_gemini,
    )
    handler = _make_handler(options=options, webhook_secret=webhook_secret)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Webhook de contratos escutando em http://{args.host}:{args.port}/webhooks/autentique")
    print("Eventos: document.created, document.finished")
    if not webhook_secret:
        print("Aviso: AUTENTIQUE_WEBHOOK_SECRET não configurado; assinatura não será validada.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando servidor.")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Automação de contratos assinados (Fase 1)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    process_parser = subparsers.add_parser("process", help="Processa documento assinado por ID")
    process_parser.add_argument("--document-id", required=True)
    process_parser.add_argument("--dry-run", action="store_true")
    process_parser.add_argument("--skip-gemini", action="store_true")
    process_parser.add_argument("--token", default="credentials/gmail-token.json")
    process_parser.set_defaults(func=_run_process_document)

    serve_parser = subparsers.add_parser("serve", help="Inicia servidor HTTP para webhooks")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve_parser.add_argument("--skip-gemini", action="store_true")
    serve_parser.add_argument("--token", default="credentials/gmail-token.json")
    serve_parser.set_defaults(func=_run_serve)

    sync_parser = subparsers.add_parser(
        "sync-controle",
        help="Cria itens faltantes no Controle Assinaturas a partir do Autentique",
    )
    sync_parser.add_argument("--dry-run", action="store_true")
    sync_parser.add_argument("--max-pages", type=int, default=50)
    sync_parser.set_defaults(func=_run_sync_controle)

    register_parser = subparsers.add_parser(
        "register-controle",
        help="Cria item no Controle Assinaturas para um documento do Autentique",
    )
    register_parser.add_argument("--document-id", required=True)
    register_parser.set_defaults(func=_run_register_controle)

    monday_parser = subparsers.add_parser(
        "serve-monday",
        help="Inicia servidor HTTP para webhooks do Monday (quadro Contratos)",
    )
    monday_parser.add_argument("--host", default="0.0.0.0")
    monday_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    monday_parser.add_argument("--skip-gemini", action="store_true")
    monday_parser.set_defaults(func=_run_serve_monday)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
