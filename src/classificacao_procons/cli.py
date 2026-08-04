"""CLI para processar e-mails do Procon-SP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from classificacao_procons.email.auth import (
    get_authorization_url,
    has_valid_token,
    save_token_from_code,
)
from classificacao_procons.email.gmail import GmailClientError, GmailProconFetcher
from classificacao_procons.health.procon_sla import (
    ProconSlaError,
    build_procon_sla_report,
    check_github_workflow_freshness,
)
from classificacao_procons.interaction_pipeline import (
    ConsumerInteractionPipelineError,
    ConsumerInteractionPipelineOptions,
    process_consumer_interactions,
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


def _run_sla_check(args: argparse.Namespace) -> int:
    if not has_valid_token(args.token):
        print("Google não conectado. Rode: procon-email auth", file=sys.stderr)
        return 1

    try:
        gmail_report = build_procon_sla_report(
            token_path=args.token,
            max_age_minutes=args.max_age_minutes,
            max_results=args.max_results,
        )
    except ProconSlaError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    workflow_report = None
    github_token = (
        args.github_token
        or os.environ.get("PROCON_ACTIONS_PAT")
        or os.environ.get("GITHUB_ACTIONS_PAT")
        or ""
    ).strip()
    if not args.skip_github_check:
        if not github_token:
            print(
                "Aviso: PROCON_ACTIONS_PAT ausente — pulando checagem do workflow.",
                file=sys.stderr,
            )
        else:
            try:
                workflow_report = check_github_workflow_freshness(
                    token=github_token,
                    max_age_minutes=args.max_workflow_age_minutes,
                    workflow_file=args.workflow_file,
                )
            except ProconSlaError as exc:
                print(json.dumps({"error": str(exc)}), file=sys.stderr)
                return 1

    stale_payload = [
        {
            "message_id": item.message_id,
            "subject": item.subject,
            "protocol_number": item.protocol_number,
            "source_id": item.source_id,
            "notification_type": item.notification_type,
            "received_at": item.received_at.isoformat(),
            "age_minutes": item.age_minutes,
        }
        for item in gmail_report.stale_notifications
    ]
    output: dict[str, object] = {
        "checked_at": gmail_report.checked_at.isoformat(),
        "gmail": {
            "max_age_minutes": gmail_report.max_age_minutes,
            "unread_scanned": gmail_report.unread_scanned,
            "stale_count": len(gmail_report.stale_notifications),
            "stale_notifications": stale_payload,
        },
    }
    if workflow_report is not None:
        output["github_workflow"] = {
            "workflow_file": workflow_report.workflow_file,
            "max_age_minutes": workflow_report.max_age_minutes,
            "last_run_created_at": (
                workflow_report.last_run_created_at.isoformat()
                if workflow_report.last_run_created_at
                else None
            ),
            "last_run_status": workflow_report.last_run_status,
            "last_run_conclusion": workflow_report.last_run_conclusion,
            "age_minutes": workflow_report.age_minutes,
            "is_stale": workflow_report.is_stale,
        }

    print(json.dumps(output, ensure_ascii=False, indent=2))

    violations: list[str] = []
    if gmail_report.stale_notifications:
        violations.append(
            f"{len(gmail_report.stale_notifications)} e-mail(s) não lido(s) acima do SLA "
            f"({gmail_report.max_age_minutes} min).",
        )
    if workflow_report is not None and workflow_report.is_stale:
        violations.append(
            "Workflow Procon automation sem run bem-sucedida recente "
            f"(limite {workflow_report.max_age_minutes} min).",
        )
    if violations:
        for line in violations:
            print(f"::error::{line}", file=sys.stderr)
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
    for key in (
        "complaint_date",
        "procon_response_deadline",
        "sac_deadline",
        "legal_deadline",
        "pa_response_deadline",
    ):
        if data.get(key) is not None:
            data[key] = data[key].isoformat()
    return data


def _parse_source_ids(value: str | None) -> tuple[str, ...] | None:
    if not value:
        return None
    source_ids = tuple(
        source_id.strip().lower() for source_id in value.split(",") if source_id.strip()
    )
    return source_ids or None


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
        source_ids=_parse_source_ids(args.sources),
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
        monday_item_ids=frozenset(args.item_id) if args.item_id else None,
    )

    try:
        results = elaborate_pending_responses(options)
    except ResponsePipelineError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    output = [_serialize_elaborated(item) for item in results]
    print(json.dumps(output, ensure_ascii=False, indent=2))

    errors = [item for item in results if item.status == "error"]
    deferred = [item for item in results if item.status == "deferred_quota"]
    if deferred:
        # Cota do Gemini esgotada: transitório, retomado na próxima execução.
        # Não derruba o run horário (evita falso vermelho no workflow).
        print(
            f"Aviso: {len(deferred)} caso(s) adiado(s) por cota do Gemini "
            "(serão retomados na próxima execução).",
            file=sys.stderr,
        )
    if not results:
        return 0
    if errors and len(errors) == len(results):
        return 1
    if errors:
        print(
            f"Aviso: {len(errors)} caso(s) falharam na elaboração; "
            f"{len(results) - len(errors)} concluído(s) com sucesso.",
            file=sys.stderr,
        )
    return 0


def _serialize_interaction(item: object) -> dict[str, object]:
    return asdict(item)


def _run_process_interactions(args: argparse.Namespace) -> int:
    if not args.dry_run and not has_valid_token(args.token):
        print("Google não conectado. Rode: procon-email auth", file=sys.stderr)
        return 1

    options = ConsumerInteractionPipelineOptions(
        max_results=args.max_results,
        mark_read=not args.no_mark_read,
        dry_run=args.dry_run,
        credentials_path=args.credentials,
        token_path=args.token,
        fetch_portal=not args.skip_portal,
        download_dir=Path(args.download_dir),
    )

    try:
        results = process_consumer_interactions(options)
    except ConsumerInteractionPipelineError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    output = [_serialize_interaction(item) for item in results]
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if any(item.status == "error" for item in results):
        return 1
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
    process_parser.add_argument(
        "--sources",
        default=None,
        help=(
            "Fontes separadas por vírgula: sp, proconsumidor, campinas, sc, alerj, uberlandia. "
            "Padrão: todas."
        ),
    )

    elaborate_parser = subparsers.add_parser(
        "elaborate",
        help="Elaborar respostas para casos com Docs SAC no Monday",
    )
    elaborate_parser.add_argument("--max-results", type=int, default=20)
    elaborate_parser.add_argument(
        "--item-id",
        action="append",
        dest="item_id",
        metavar="MONDAY_ITEM_ID",
        help="Elaborar só estes itens do Monday (pode repetir a flag).",
    )
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

    interactions_parser = subparsers.add_parser(
        "process-interactions",
        help="Interação do consumidor (Procon-SP): update no Monday, sem novo item",
    )
    interactions_parser.add_argument("--max-results", type=int, default=20)
    interactions_parser.add_argument("--download-dir", default="downloads")
    interactions_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Só lista os e-mails que seriam processados.",
    )
    interactions_parser.add_argument(
        "--no-mark-read",
        action="store_true",
        help="Não marca os e-mails como lidos após sucesso.",
    )
    interactions_parser.add_argument(
        "--skip-portal",
        action="store_true",
        help="Não abre o portal (só e-mail + anexos no update).",
    )

    sla_parser = subparsers.add_parser(
        "sla-check",
        help="Verificar SLA: e-mails não lidos e última run do GitHub Actions",
    )
    sla_parser.add_argument(
        "--max-age-minutes",
        type=int,
        default=90,
        help="Alerta se e-mail de reclamação não lido for mais antigo que isto (padrão 90).",
    )
    sla_parser.add_argument(
        "--max-workflow-age-minutes",
        type=int,
        default=150,
        help="Alerta se não houver run verde do workflow há mais que isto (padrão 150).",
    )
    sla_parser.add_argument("--max-results", type=int, default=50)
    sla_parser.add_argument(
        "--workflow-file",
        default="procon-hourly.yml",
        help="Arquivo do workflow no repositório (padrão procon-hourly.yml).",
    )
    sla_parser.add_argument(
        "--github-token",
        default=None,
        help="PAT com Actions read (ou PROCON_ACTIONS_PAT / GITHUB_ACTIONS_PAT no ambiente).",
    )
    sla_parser.add_argument(
        "--skip-github-check",
        action="store_true",
        help="Só checar Gmail (sem API do GitHub).",
    )

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
    if args.command == "process-interactions":
        return _run_process_interactions(args)
    if args.command == "sla-check":
        return _run_sla_check(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
