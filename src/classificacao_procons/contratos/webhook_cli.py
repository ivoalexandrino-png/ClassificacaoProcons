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
from classificacao_procons.contratos.pipeline import (
    ContractPipelineError,
    ContractPipelineOptions,
    process_finished_document,
    process_finished_webhook_event,
)

ENV_WEBHOOK_SECRET = "AUTENTIQUE_WEBHOOK_SECRET"
DEFAULT_PORT = 8080


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

            if event.event_type != "document.finished":
                return

            def _process() -> None:
                try:
                    process_finished_webhook_event(event, options=options)
                except ContractPipelineError:
                    return

            threading.Thread(target=_process, daemon=True).start()

    return WebhookHandler


def _run_serve(args: argparse.Namespace) -> int:
    webhook_secret = os.environ.get(ENV_WEBHOOK_SECRET, "").strip() or None
    options = ContractPipelineOptions(
        token_path=args.token,
        skip_gemini=args.skip_gemini,
    )
    handler = _make_handler(options=options, webhook_secret=webhook_secret)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Webhook de contratos escutando em http://{args.host}:{args.port}/webhooks/autentique")
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

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
