"""CLI e servidor HTTP para webhooks de contratos."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from classificacao_procons.contratos.autentique.client import AutentiqueClientError
from classificacao_procons.contratos.autentique.webhook import (
    AutentiqueWebhookError,
    parse_webhook_event,
    verify_webhook_signature,
)
from classificacao_procons.contratos.autentique.webhook_endpoints import (
    ensure_contratos_autentique_webhooks,
)
from classificacao_procons.contratos.catch_up import CatchUpError, catch_up_contratos
from classificacao_procons.contratos.contratos_enrichment import (
    ContratosEnrichmentError,
    process_contratos_item_created,
)
from classificacao_procons.contratos.controle_link_suggestions import apply_controle_link_suggestion
from classificacao_procons.contratos.controle_sync import (
    ControleSyncError,
    compare_autentique_with_controle,
    process_document_created_webhook_event,
    process_signature_accepted_webhook_event,
    process_signature_rejected_webhook_event,
    register_document_in_controle,
    sync_controle_from_autentique,
)
from classificacao_procons.contratos.monday_contracts import build_controle_assinaturas_index
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
from classificacao_procons.monday.client import get_api_token_from_env

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
    if event.event_type == "signature.accepted":
        process_signature_accepted_webhook_event(
            event,
            monday_api_token=options.monday_api_token,
            autentique_api_token=options.autentique_api_token,
        )
        return
    if event.event_type == "signature.rejected":
        process_signature_rejected_webhook_event(
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
        result = sync_controle_from_autentique(
            dry_run=args.dry_run,
            max_pages=args.max_pages,
            update_existing=not args.create_only,
            skip_signed_documents=args.skip_signed_documents,
            auto_link_legacy=not args.no_auto_link_legacy,
            allow_create=True if args.allow_create else None,
        )
    except ControleSyncError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    summary = {
        "total_autentique": result.total_autentique,
        "already_in_monday": result.already_in_monday,
        "created": result.created,
        "updated": result.updated,
        "skipped": result.skipped,
        "deferred_signed": result.deferred_signed,
        "failed": result.failed,
        "dry_run": result.dry_run,
        "legacy_linked": result.legacy_linked,
        "legacy_link_would_apply": result.legacy_link_would_apply,
        "legacy_link_ambiguous_skipped": result.legacy_link_ambiguous_skipped,
        "legacy_link_failed": result.legacy_link_failed,
        "create_paused": result.create_paused,
        "items": [
            item.__dict__
            for item in result.items
            if item.action
            not in ("already_exists", "unchanged")
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result.failed == 0 else 1


def _run_compare_controle(args: argparse.Namespace) -> int:
    try:
        result = compare_autentique_with_controle(max_pages=args.max_pages)
    except ControleSyncError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    summary = {
        "autentique_total": result.autentique_total,
        "monday_items_total": result.monday_items_total,
        "pending_missing_in_monday_count": len(result.pending_missing_in_monday),
        "signed_missing_in_monday_count": len(result.signed_missing_in_monday),
        "monday_without_autentique_link_count": len(result.monday_without_autentique_link),
        "monday_autentique_id_not_in_feed_count": len(result.monday_autentique_id_not_in_feed),
        "duplicate_autentique_ids_count": len(result.duplicate_autentique_ids),
        "duplicate_normalized_names_count": len(result.duplicate_normalized_names),
        "monday_status_behind_autentique_count": len(result.monday_status_behind_autentique),
        "monday_track_status_mismatch_count": len(result.monday_track_status_mismatch),
        "legacy_link_suggestions_count": len(result.legacy_link_suggestions),
        "pending_missing_in_monday": [
            {"document_id": doc_id, "document_name": name}
            for doc_id, name in result.pending_missing_in_monday[:200]
        ],
        "signed_missing_in_monday": [
            {"document_id": doc_id, "document_name": name}
            for doc_id, name in result.signed_missing_in_monday[:50]
        ],
        "monday_without_autentique_link": [
            {"item_id": item_id, "name": name, "status": status}
            for item_id, name, status in result.monday_without_autentique_link[:100]
        ],
        "monday_autentique_id_not_in_feed": [
            {"item_id": item_id, "name": name, "autentique_id": doc_id}
            for item_id, name, doc_id in result.monday_autentique_id_not_in_feed[:100]
        ],
        "duplicate_autentique_ids": [
            {"autentique_id": doc_id, "monday_item_ids": list(item_ids)}
            for doc_id, item_ids in result.duplicate_autentique_ids[:50]
        ],
        "duplicate_normalized_names": [
            {
                "normalized_title": title,
                "items": [{"item_id": i, "name": n} for i, n in entries],
            }
            for title, entries in result.duplicate_normalized_names[:30]
        ],
        "monday_status_behind_autentique": [
            {
                "item_id": item_id,
                "name": name,
                "autentique_id": doc_id,
                "monday_status": status,
                "expected_status": expected,
            }
            for item_id, name, doc_id, status, expected in result.monday_status_behind_autentique[
                :100
            ]
        ],
        "monday_track_status_mismatch": [
            {
                "item_id": item_id,
                "name": name,
                "autentique_id": doc_id,
                "track": track,
                "monday_status": status,
                "expected_status": expected,
            }
            for item_id, name, doc_id, track, status, expected in (
                result.monday_track_status_mismatch[:200]
            )
        ],
        "legacy_link_suggestions": [
            {
                "monday_item_id": row.monday_item_id,
                "monday_item_name": row.monday_item_name,
                "monday_status": row.monday_status,
                "autentique_document_id": row.autentique_document_id,
                "autentique_document_name": row.autentique_document_name,
                "match_reason": row.match_reason,
                "confidence": row.confidence,
                "autentique_fully_signed": row.autentique_fully_signed,
            }
            for row in result.legacy_link_suggestions[:200]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _run_link_controle(args: argparse.Namespace) -> int:
    monday_token = get_api_token_from_env()
    if not monday_token:
        print("Erro: MONDAY_API_TOKEN não configurada.", file=sys.stderr)
        return 1
    try:
        index = build_controle_assinaturas_index(api_token=monday_token)
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "monday_item_id": args.monday_item_id,
                        "document_id": args.document_id,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            return 0
        linked = apply_controle_link_suggestion(
            api_token=monday_token,
            monday_item_id=args.monday_item_id,
            document_id=args.document_id,
            index=index,
        )
    except (ControleSyncError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"linked_item_ids": list(linked)}, ensure_ascii=False, indent=2))
    return 0


def _run_register_autentique_webhook(args: argparse.Namespace) -> int:
    try:
        result = ensure_contratos_autentique_webhooks(base_service_url=args.base_url)
    except AutentiqueClientError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    payload = {
        "webhook_url": result.webhook_url,
        "organization_id": result.organization_id,
        "webhook_secret": result.webhook_secret,
        "document_endpoint": (
            result.document_endpoint.__dict__ if result.document_endpoint else None
        ),
        "signature_endpoint": (
            result.signature_endpoint.__dict__ if result.signature_endpoint else None
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run_sync_all(args: argparse.Namespace) -> int:
    try:
        result = catch_up_contratos(
            dry_run=args.dry_run,
            max_pages=args.max_pages,
            skip_gemini=args.skip_gemini,
            token_path=args.token,
            process_signed=not args.sync_controle_only,
        )
    except CatchUpError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    summary = {
        "sync_created": result.sync_created,
        "sync_updated": result.sync_updated,
        "sync_failed": result.sync_failed,
        "signed_total": result.signed_total,
        "processed": result.processed,
        "skipped": result.skipped,
        "process_failed": result.process_failed,
        "dry_run": result.dry_run,
        "items": [item.__dict__ for item in result.items if item.action != "skipped"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result.sync_failed == 0 and result.process_failed == 0 else 1


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

            supported_events = (
                "document.created",
                "signature.accepted",
                "signature.rejected",
                "document.finished",
            )
            if event.event_type not in supported_events:
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
    print("Eventos: document.created, signature.accepted, document.finished")
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
        help="Cria ou atualiza itens no Controle Assinaturas a partir do Autentique",
    )
    sync_parser.add_argument("--dry-run", action="store_true")
    sync_parser.add_argument("--max-pages", type=int, default=50)
    sync_parser.add_argument(
        "--create-only",
        action="store_true",
        help="Não atualiza itens existentes (somente cria faltantes)",
    )
    sync_parser.add_argument(
        "--skip-signed-documents",
        action="store_true",
        help="Não cria itens já totalmente assinados no Autentique (próxima fase)",
    )
    sync_parser.add_argument(
        "--no-auto-link-legacy",
        action="store_true",
        help="Não vincula automaticamente itens legados com título exato inequívoco",
    )
    sync_parser.add_argument(
        "--allow-create",
        action="store_true",
        help="Permite criar novos itens no Controle (padrão: criação pausada)",
    )
    sync_parser.set_defaults(func=_run_sync_controle)

    compare_parser = subparsers.add_parser(
        "compare-controle",
        help="Compara Autentique e Controle Assinaturas sem alterar Monday",
    )
    compare_parser.add_argument("--max-pages", type=int, default=50)
    compare_parser.set_defaults(func=_run_compare_controle)

    link_parser = subparsers.add_parser(
        "link-controle",
        help="Grava Autentique ID em item legado do Controle (confirmação humana)",
    )
    link_parser.add_argument("--monday-item-id", required=True)
    link_parser.add_argument("--document-id", required=True)
    link_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Só valida parâmetros; não grava no Monday",
    )
    link_parser.set_defaults(func=_run_link_controle)

    sync_all_parser = subparsers.add_parser(
        "sync-all",
        help="Sincroniza Controle Assinaturas e processa contratos totalmente assinados",
    )
    sync_all_parser.add_argument("--dry-run", action="store_true")
    sync_all_parser.add_argument("--max-pages", type=int, default=50)
    sync_all_parser.add_argument("--skip-gemini", action="store_true")
    sync_all_parser.add_argument("--token", default="credentials/gmail-token.json")
    sync_all_parser.add_argument(
        "--sync-controle-only",
        action="store_true",
        help="Somente sincroniza Controle Assinaturas (não processa assinados)",
    )
    sync_all_parser.set_defaults(func=_run_sync_all)

    register_parser = subparsers.add_parser(
        "register-controle",
        help="Cria item no Controle Assinaturas para um documento do Autentique",
    )
    register_parser.add_argument("--document-id", required=True)
    register_parser.set_defaults(func=_run_register_controle)

    autentique_wh_parser = subparsers.add_parser(
        "register-autentique-webhook",
        help="Registra endpoints de webhook no Autentique (API) para o Cloud Run",
    )
    autentique_wh_parser.add_argument(
        "--base-url",
        required=True,
        help="URL base do Cloud Run (sem /webhooks/autentique)",
    )
    autentique_wh_parser.set_defaults(func=_run_register_autentique_webhook)

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
