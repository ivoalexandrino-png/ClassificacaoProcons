"""CLI para processar e-mails do Procon-SP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from classificacao_procons.email import GmailClientError, GmailProconFetcher
from classificacao_procons.email.auth import (
    get_authorization_url,
    has_valid_token,
    save_token_from_code,
)
from classificacao_procons.pipeline import (
    PipelineError,
    PipelineOptions,
    process_new_complaints,
    register_monday_for_access_code,
)
from classificacao_procons.response_pipeline import (
    ResponsePipelineError,
    ResponsePipelineOptions,
    elaborate_pending_responses,
)


def _default_credentials_path() -> str:
    return os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials/gmail-oauth.json")


def _default_token_path() -> str:
    return os.environ.get("GMAIL_TOKEN_PATH", "credentials/gmail-token.json")


def _serialize_notification(notification: object) -> dict[str, object]:
    data = asdict(notification)
    if "received_at" in data:
        data["received_at"] = data["received_at"].isoformat()
    return data


def _run_auth(args: argparse.Namespace) -> int:
    credentials = args.credentials
    token = args.token

    if args.code:
        try:
            save_token_from_code(
                code=args.code,
                credentials_path=credentials,
                token_path=token,
                remote=args.remote,
            )
        except GmailClientError as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            return 1
        print("Pronto! Gmail e Drive conectados com sucesso.")
        return 0

    if has_valid_token(token) and not args.remote:
        print("Gmail e Drive já estão conectados.")
        return 0

    try:
        url = get_authorization_url(
            credentials_path=credentials,
            remote=args.remote,
        )
    except GmailClientError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    if args.remote:
        print("Link para autorizar Gmail e Drive (use no GitHub Actions):\n")
        print(url)
        print(
            "\nDepois de Permitir, copie o código da barra de endereço "
            "e rode o workflow 'Setup Google token' com esse código.",
        )
        return 0

    print("Para conectar Gmail e Drive, siga estes 4 passos:\n")
    print("1. Abra este link no navegador:")
    print(f"\n   {url}\n")
    print("2. Faça login com a conta que recebe os e-mails do Procon")
    print("3. Clique em Permitir")
    print("4. A página pode dar erro ou ficar em branco — isso é normal.")
    print("   Olhe a barra de endereço do navegador.")
    print("   Copie o texto que vem depois de code= (até o próximo &).")
    print("\nExemplo: se aparecer localhost/?code=4/0ABC123&scope=...")
    print("         copie só: 4/0ABC123")
    print("\nCole o código aqui no chat.")
    return 0


def _serialize_processed(item: object) -> dict[str, object]:
    data = asdict(item)
    for key in ("complaint_date", "procon_response_deadline", "sac_deadline", "legal_deadline"):
        if data.get(key) is not None:
            data[key] = data[key].isoformat()
    return data


def _run_process(args: argparse.Namespace) -> int:
    if not args.dry_run and not has_valid_token(args.token):
        print("Google não conectado. Rode: procon-email auth", file=sys.stderr)
        return 1

    options = PipelineOptions(
        max_results=args.max_results,
        download_dir=Path(args.download_dir),
        mark_read=not args.no_mark_read,
        dry_run=args.dry_run,
        credentials_path=args.credentials,
        token_path=args.token,
    )

    try:
        results = process_new_complaints(options)
    except PipelineError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    output = [_serialize_processed(item) for item in results]
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if any(item.status == "error" for item in results):
        return 1
    if any(item.monday_error for item in results):
        return 1
    return 0


def _run_register_monday(args: argparse.Namespace) -> int:
    if not has_valid_token(args.token):
        print("Google não conectado. Rode: procon-email auth", file=sys.stderr)
        return 1

    options = PipelineOptions(
        download_dir=Path(args.download_dir),
        credentials_path=args.credentials,
        token_path=args.token,
    )
    try:
        result = register_monday_for_access_code(args.access_code, options=options)
    except PipelineError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    print(json.dumps(_serialize_processed(result), ensure_ascii=False, indent=2))
    return 0


def _serialize_elaborated(item: object) -> dict[str, object]:
    return asdict(item)


def _run_elaborate(args: argparse.Namespace) -> int:
    if not args.dry_run and not has_valid_token(args.token):
        print("Google não conectado. Rode: procon-email auth", file=sys.stderr)
        return 1

    options = ResponsePipelineOptions(
        work_dir=Path(args.work_dir),
        max_cases=args.max_results,
        dry_run=args.dry_run,
        token_path=args.token,
    )

    try:
        results = elaborate_pending_responses(options)
    except ResponsePipelineError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    output = [_serialize_elaborated(item) for item in results]
    print(json.dumps(output, ensure_ascii=False, indent=2))

    errors = [item for item in results if item.status == "error"]
    if not results:
        return 0
    if len(errors) == len(results):
        return 1
    if errors:
        print(
            f"Aviso: {len(errors)} caso(s) falharam na elaboração; "
            f"{len(results) - len(errors)} concluído(s) com sucesso.",
            file=sys.stderr,
        )
    return 0


def _run_list(args: argparse.Namespace) -> int:
    if not has_valid_token(args.token):
        print(
            "Gmail ainda não conectado. Rode: procon-email auth",
            file=sys.stderr,
        )
        return 1

    try:
        fetcher = GmailProconFetcher.from_credentials(
            credentials_path=args.credentials,
            token_path=args.token,
        )
        notifications = fetcher.list_unread_notifications(max_results=args.max_results)
    except GmailClientError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    output = [_serialize_notification(item) for item in notifications]
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if args.mark_read:
        for notification in notifications:
            fetcher.mark_as_read(notification.message_id)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Agente Procon-SP — conecta Gmail e lê notificações de CIP.",
    )
    parser.add_argument(
        "--credentials",
        default=_default_credentials_path(),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--token",
        default=_default_token_path(),
        help=argparse.SUPPRESS,
    )

    subparsers = parser.add_subparsers(dest="command")

    auth_parser = subparsers.add_parser("auth", help="Conectar sua conta Gmail")
    auth_parser.add_argument(
        "--code",
        help="Código de autorização copiado do Google (uso interno).",
    )
    auth_parser.add_argument(
        "--remote",
        action="store_true",
        help="Fluxo para GitHub Actions (sem pasta credentials no PC).",
    )

    list_parser = subparsers.add_parser("list", help="Listar e-mails do Procon não lidos")
    list_parser.add_argument("--max-results", type=int, default=20)
    list_parser.add_argument("--mark-read", action="store_true")

    process_parser = subparsers.add_parser(
        "process",
        help="Processar e-mails novos: portal + Drive",
    )
    process_parser.add_argument("--max-results", type=int, default=20)
    process_parser.add_argument("--download-dir", default="downloads")
    process_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Só lista os e-mails que seriam processados.",
    )
    process_parser.add_argument(
        "--no-mark-read",
        action="store_true",
        help="Não marca os e-mails como lidos após sucesso.",
    )

    elaborate_parser = subparsers.add_parser(
        "elaborate",
        help="Elaborar respostas para casos com Docs SAC no Monday",
    )
    elaborate_parser.add_argument("--max-results", type=int, default=20)
    elaborate_parser.add_argument("--work-dir", default="downloads/elaboration")
    elaborate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Só lista os casos que seriam elaborados.",
    )

    register_monday_parser = subparsers.add_parser(
        "register-monday",
        help="Cadastrar no Monday um caso já salvo no Drive",
    )
    register_monday_parser.add_argument(
        "--access-code",
        required=True,
        help="Código de acesso do portal Procon (do e-mail de notificação).",
    )
    register_monday_parser.add_argument("--download-dir", default="downloads")

    args = parser.parse_args(argv)

    if args.command == "auth":
        return _run_auth(args)
    if args.command == "list":
        return _run_list(args)
    if args.command == "process":
        return _run_process(args)
    if args.command == "elaborate":
        return _run_elaborate(args)
    if args.command == "register-monday":
        return _run_register_monday(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
