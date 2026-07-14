"""CLI para processar e-mails do Procon-SP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from classificacao_procons.email import GmailClientError, GmailProconFetcher


def _default_credentials_path() -> str:
    return os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials/gmail-oauth.json")


def _default_token_path() -> str:
    return os.environ.get("GMAIL_TOKEN_PATH", "credentials/gmail-token.json")


def _serialize_notification(notification: object) -> dict[str, object]:
    data = asdict(notification)
    if "received_at" in data:
        data["received_at"] = data["received_at"].isoformat()
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Busca e-mails de notificação CIP do Procon-SP no Gmail.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=20,
        help="Número máximo de e-mails não lidos a processar (padrão: 20).",
    )
    parser.add_argument(
        "--mark-read",
        action="store_true",
        help="Marca os e-mails processados como lidos.",
    )
    parser.add_argument(
        "--credentials",
        default=_default_credentials_path(),
        help="Caminho do JSON OAuth do Gmail (client secrets).",
    )
    parser.add_argument(
        "--token",
        default=_default_token_path(),
        help="Caminho do token OAuth salvo após autorização.",
    )
    args = parser.parse_args(argv)

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


if __name__ == "__main__":
    raise SystemExit(main())
