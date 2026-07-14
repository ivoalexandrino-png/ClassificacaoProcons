"""CLI para processar e-mails do Procon-SP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from classificacao_procons.email import GmailClientError, GmailProconFetcher
from classificacao_procons.email.auth import (
    get_authorization_url,
    has_valid_token,
    save_token_from_code,
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
            )
        except GmailClientError as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            return 1
        print("Pronto! Seu Gmail foi conectado com sucesso.")
        return 0

    if has_valid_token(token):
        print("Seu Gmail já está conectado.")
        return 0

    try:
        url = get_authorization_url(credentials_path=credentials)
    except GmailClientError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    print("Para conectar seu Gmail, siga estes 3 passos:\n")
    print("1. Abra este link no navegador:")
    print(f"\n   {url}\n")
    print("2. Faça login com a conta que recebe os e-mails do Procon")
    print("3. Clique em Permitir e copie o código que aparecer")
    print("\nDepois me envie o código aqui no chat.")
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

    list_parser = subparsers.add_parser("list", help="Listar e-mails do Procon não lidos")
    list_parser.add_argument("--max-results", type=int, default=20)
    list_parser.add_argument("--mark-read", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "auth":
        return _run_auth(args)
    if args.command == "list":
        return _run_list(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
