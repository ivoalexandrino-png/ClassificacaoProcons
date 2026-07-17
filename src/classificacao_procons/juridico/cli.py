"""CLI do agente jurídico (procon-juridico)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from classificacao_procons.email import GmailClientError
from classificacao_procons.email.auth import (
    get_authorization_url,
    has_valid_token,
    save_token_from_code,
)
from classificacao_procons.google_auth import GoogleAuthError
from classificacao_procons.juridico.gmail import GmailIntimacaoFetcher
from classificacao_procons.juridico.models import IntimacaoEmail
from classificacao_procons.juridico.parser import (
    IntimacaoParseError,
    parse_intimacao_body,
)
from classificacao_procons.juridico.pipeline import (
    JuridicoPipelineError,
    JuridicoPipelineOptions,
    process_new_intimacoes,
)
from classificacao_procons.juridico.providencia import classify_providencia


def _default_credentials_path() -> str:
    return os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials/gmail-oauth.json")


def _default_token_path() -> str:
    return os.environ.get("GMAIL_TOKEN_PATH", "credentials/gmail-token.json")


def _jsonify(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _serialize(data: dict[str, object]) -> dict[str, object]:
    return {key: _jsonify(value) for key, value in data.items()}


def _run_parse(args: argparse.Namespace) -> int:
    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(json.dumps({"error": f"Arquivo não encontrado: {path}"}), file=sys.stderr)
            return 1
        content = path.read_text(encoding="utf-8", errors="replace")
        is_html = args.html or path.suffix.lower() in {".html", ".htm"}
    else:
        content = sys.stdin.read()
        is_html = args.html

    if not content.strip():
        print(json.dumps({"error": "Corpo do e-mail vazio."}), file=sys.stderr)
        return 1

    try:
        parsed = parse_intimacao_body(
            html=content if is_html else None,
            text=None if is_html else content,
        )
    except IntimacaoParseError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    intimacao = IntimacaoEmail(
        message_id="cli-parse",
        subject=args.subject or "",
        sender="",
        received_at=datetime.now(),
        process_number=parsed.process_number,
        tribunal=parsed.tribunal,
        vara=parsed.vara,
        movement_type=parsed.movement_type,
        prazo_dias=parsed.prazo_dias,
        prazo_uteis=parsed.prazo_uteis,
        publication_date=parsed.publication_date,
        hearing_at=parsed.hearing_at,
        portal_url=parsed.portal_url,
        body_excerpt=parsed.body_excerpt,
    )
    providencia = classify_providencia(intimacao)

    output = {
        "intimacao": _serialize(asdict(parsed)),
        "providencia": _serialize(asdict(providencia)),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def _run_list(args: argparse.Namespace) -> int:
    if not has_valid_token(args.token):
        print("Google não conectado. Rode: procon-juridico auth", file=sys.stderr)
        return 1
    try:
        fetcher = GmailIntimacaoFetcher.from_credentials(
            credentials_path=args.credentials,
            token_path=args.token,
        )
        intimacoes = fetcher.list_unread_intimacoes(max_results=args.max_results)
    except GmailClientError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    output = [_serialize(asdict(item)) for item in intimacoes]
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if args.mark_read:
        for item in intimacoes:
            fetcher.mark_as_read(item.message_id)
    return 0


def _run_process(args: argparse.Namespace) -> int:
    if not args.dry_run and not has_valid_token(args.token):
        print("Google não conectado. Rode: procon-juridico auth", file=sys.stderr)
        return 1

    options = JuridicoPipelineOptions(
        max_results=args.max_results,
        mark_read=not args.no_mark_read,
        dry_run=args.dry_run,
        credentials_path=args.credentials,
        token_path=args.token,
    )
    try:
        results = process_new_intimacoes(options)
    except JuridicoPipelineError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    output = [_serialize(asdict(item)) for item in results]
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if any(item.status == "error" for item in results):
        return 1
    if any(item.monday_error for item in results):
        return 1
    return 0


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
        except (GmailClientError, GoogleAuthError) as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            return 1
        print("Pronto! Gmail e Drive conectados com sucesso.")
        return 0

    if has_valid_token(token) and not args.remote:
        print("Gmail e Drive já estão conectados.")
        return 0

    try:
        url = get_authorization_url(credentials_path=credentials, remote=args.remote)
    except (GmailClientError, GoogleAuthError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    print("Para conectar o Gmail que recebe as intimações, abra o link, autorize")
    print("e cole aqui o código que aparece após 'code=' na barra de endereço:\n")
    print(url)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Agente jurídico — lê intimações do Gmail, acompanha o andamento e "
            "registra prazos e audiências no Monday."
        ),
    )
    parser.add_argument(
        "--credentials",
        default=_default_credentials_path(),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--token", default=_default_token_path(), help=argparse.SUPPRESS)

    subparsers = parser.add_subparsers(dest="command")

    parse_parser = subparsers.add_parser(
        "parse",
        help="Extrair dados de uma intimação (offline) de um arquivo ou stdin",
    )
    parse_parser.add_argument("--file", help="Arquivo .html ou .txt com o corpo do e-mail.")
    parse_parser.add_argument("--html", action="store_true", help="Tratar a entrada como HTML.")
    parse_parser.add_argument("--subject", help="Assunto do e-mail (opcional).")

    list_parser = subparsers.add_parser("list", help="Listar intimações não lidas no Gmail")
    list_parser.add_argument("--max-results", type=int, default=20)
    list_parser.add_argument("--mark-read", action="store_true")

    process_parser = subparsers.add_parser(
        "process",
        help="Processar intimações novas: andamento + providência + Monday",
    )
    process_parser.add_argument("--max-results", type=int, default=20)
    process_parser.add_argument("--dry-run", action="store_true")
    process_parser.add_argument("--no-mark-read", action="store_true")

    auth_parser = subparsers.add_parser("auth", help="Conectar a conta Gmail que recebe intimações")
    auth_parser.add_argument("--code", help="Código de autorização copiado do Google.")
    auth_parser.add_argument("--remote", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "parse":
        return _run_parse(args)
    if args.command == "list":
        return _run_list(args)
    if args.command == "process":
        return _run_process(args)
    if args.command == "auth":
        return _run_auth(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
