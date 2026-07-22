"""CLI do agente jurídico: intimações, andamentos e providências."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from classificacao_procons.email.gmail import GmailClientError
from classificacao_procons.google_auth import has_valid_token
from classificacao_procons.juridico.cnj import extract_process_number
from classificacao_procons.juridico.comunica import ComunicaError, fetch_case_communications
from classificacao_procons.juridico.datajud import DataJudError, fetch_case_movements
from classificacao_procons.juridico.events import AgentEventError, list_events
from classificacao_procons.juridico.gmail import GmailJuridicoFetcher
from classificacao_procons.juridico.monday import MondayClientError, describe_boards
from classificacao_procons.juridico.pipeline import (
    JuridicoPipelineError,
    JuridicoPipelineOptions,
    process_new_intimacoes,
)

AUTH_HINT = "Google não conectado. Rode: procon-email auth"


def _default_credentials_path() -> str:
    return os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials/gmail-oauth.json")


def _default_token_path() -> str:
    return os.environ.get("GMAIL_TOKEN_PATH", "credentials/gmail-token.json")


def _serialize(value: object) -> object:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _serialize_dataclass(item: object) -> dict[str, object]:
    return {key: _serialize(value) for key, value in asdict(item).items()}


def _run_list(args: argparse.Namespace) -> int:
    if not has_valid_token(args.token):
        print(AUTH_HINT, file=sys.stderr)
        return 1

    try:
        fetcher = GmailJuridicoFetcher.from_credentials(
            credentials_path=args.credentials,
            token_path=args.token,
        )
        notifications = fetcher.list_unread_notifications(max_results=args.max_results)
    except GmailClientError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    output = [
        {
            "message_id": item.message_id,
            "subject": item.subject,
            "sender": item.sender,
            "received_at": item.received_at.isoformat(),
            "process_number": extract_process_number(f"{item.subject}\n{item.body_text}"),
        }
        for item in notifications
    ]
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def _run_process(args: argparse.Namespace) -> int:
    if not args.dry_run and not has_valid_token(args.token):
        print(AUTH_HINT, file=sys.stderr)
        return 1

    options = JuridicoPipelineOptions(
        max_results=args.max_results,
        mark_read=not args.no_mark_read,
        dry_run=args.dry_run,
        credentials_path=args.credentials,
        token_path=args.token,
        consult_datajud=not args.no_datajud,
        consult_comunica=not args.no_comunica,
    )

    try:
        results = process_new_intimacoes(options)
    except JuridicoPipelineError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    output = [_serialize_dataclass(item) for item in results]
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if any(item.status == "error" for item in results):
        return 1
    if any(item.monday_error for item in results):
        return 1
    return 0


def _run_comunicacoes(args: argparse.Namespace) -> int:
    try:
        communications = fetch_case_communications(args.numero, limit=args.limit)
    except ComunicaError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    output = [_serialize_dataclass(item) for item in communications]
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def _run_andamentos(args: argparse.Namespace) -> int:
    try:
        movements = fetch_case_movements(
            args.numero,
            alias=args.alias,
            limit=args.limit,
        )
    except DataJudError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    output = [_serialize_dataclass(item) for item in movements]
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def _run_portal(args: argparse.Namespace) -> int:
    from classificacao_procons.juridico.acessos import (
        AcessosError,
        get_tribunal_credential,
    )
    from classificacao_procons.juridico.cnj import tribunal_acronym
    from classificacao_procons.juridico.portais.esaj import (
        PortalError,
        PortalRequiresInteraction,
        fetch_process_content,
        fetch_process_content_public,
    )
    from classificacao_procons.juridico.portais.token_email import gmail_token_provider

    acronym = args.tribunal or tribunal_acronym(args.numero)
    if not acronym:
        print(json.dumps({"error": "Tribunal não identificado pelo número CNJ."}), file=sys.stderr)
        return 1

    # O mesmo tribunal pode ter vários sistemas (e-SAJ, PJe, Projudi, eproc); o
    # DataJud informa qual sistema indexa este processo. Só e-SAJ (SAJ) é
    # suportado no scraping; os demais são reportados claramente.
    sistema = None
    try:
        from classificacao_procons.juridico.datajud import DataJudError, fetch_case_metadata

        metadata = fetch_case_metadata(args.numero)
        sistema = metadata.sistema if metadata else None
    except DataJudError:
        sistema = None
    if sistema and "SAJ" not in sistema.upper():
        print(
            json.dumps(
                {
                    "unsupported_system": sistema,
                    "info": (
                        f"Processo tramita no sistema {sistema}; o scraping de portal "
                        "cobre só e-SAJ por ora. Andamentos seguem pelo DataJud."
                    ),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    content = None
    secrecy = False

    # 1) Consulta pública primeiro (sem login, sem 2FA) — cobre a maioria.
    if not args.autenticado:
        try:
            content = fetch_process_content_public(args.numero, headless=not args.headed)
        except PortalRequiresInteraction as exc:
            secrecy = True
            print(
                json.dumps({"info": f"Consulta pública indisponível: {exc}"}, ensure_ascii=False),
                file=sys.stderr,
            )
        except PortalError as exc:
            print(
                json.dumps({"info": f"Consulta pública falhou: {exc}"}, ensure_ascii=False),
                file=sys.stderr,
            )

    # 2) Fallback autenticado (segredo de justiça / --autenticado).
    if content is None and (secrecy or args.autenticado):
        try:
            credential = get_tribunal_credential(acronym)
        except AcessosError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        if credential is None:
            print(
                json.dumps(
                    {"error": f"Sem credencial de portal para {acronym} no quadro Acessos."},
                ),
                file=sys.stderr,
            )
            return 2 if secrecy else 1
        if "SAJ" not in credential.system:
            message = f"Portal {credential.system} de {acronym} ainda não suportado (só e-SAJ)."
            print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
            return 1

        token_provider = None
        if args.token_email:
            token_provider = lambda login: gmail_token_provider(  # noqa: E731
                login,
                token_path=args.token,
            )
        elif args.token_code:
            token_provider = lambda _login: args.token_code  # noqa: E731

        try:
            content = fetch_process_content(
                args.numero,
                credential=credential,
                headless=not args.headed,
                token_provider=token_provider,
            )
        except PortalRequiresInteraction as exc:
            print(json.dumps({"needs_interaction": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 2
        except PortalError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 1

    if content is None:
        print(
            json.dumps({"needs_interaction": "Consulta pública sem dados."}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            {
                "process_number": content.process_number,
                "source": content.source,
                "classe": content.classe,
                "assunto": content.assunto,
                "situacao": content.situacao,
                "movements": content.movements,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return 0


def _run_boards(args: argparse.Namespace) -> int:
    try:
        boards = describe_boards(name_filter=args.filter)
    except MondayClientError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    print(json.dumps(boards, ensure_ascii=False, indent=2))
    return 0


def _run_events(args: argparse.Namespace) -> int:
    try:
        events = list_events(
            events_path=Path(args.events_path),
            event_type=args.type,
        )
    except AgentEventError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    output = [_serialize_dataclass(item) for item in events]
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Agente jurídico — lê intimações (e-mail/push), consulta andamento "
            "processual (DataJud) e cadastra providências, prazos e audiências no Monday."
        ),
    )
    parser.add_argument(
        "--credentials",
        default=_default_credentials_path(),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--token", default=_default_token_path(), help=argparse.SUPPRESS)

    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", help="Listar intimações não lidas")
    list_parser.add_argument("--max-results", type=int, default=20)

    process_parser = subparsers.add_parser(
        "process",
        help="Processar intimações novas: triagem + Monday + eventos",
    )
    process_parser.add_argument("--max-results", type=int, default=20)
    process_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Só mostra a triagem (consultando DataJud/Comunica, somente leitura), "
            "sem Monday, eventos ou marcação de lido."
        ),
    )
    process_parser.add_argument(
        "--no-mark-read",
        action="store_true",
        help="Não marca os e-mails como lidos após sucesso.",
    )
    process_parser.add_argument(
        "--no-datajud",
        action="store_true",
        help="Não consulta o andamento processual no DataJud.",
    )
    process_parser.add_argument(
        "--no-comunica",
        action="store_true",
        help="Não busca o teor das comunicações no Domicílio Judicial (Comunica).",
    )

    comunicacoes_parser = subparsers.add_parser(
        "comunicacoes",
        help="Consultar o teor das comunicações no Domicílio Judicial Eletrônico",
    )
    comunicacoes_parser.add_argument(
        "--numero",
        required=True,
        help="Número do processo no formato CNJ.",
    )
    comunicacoes_parser.add_argument("--limit", type=int, default=5)

    andamentos_parser = subparsers.add_parser(
        "andamentos",
        help="Consultar andamento processual na API pública do DataJud",
    )
    andamentos_parser.add_argument(
        "--numero",
        required=True,
        help="Número do processo no formato CNJ.",
    )
    andamentos_parser.add_argument(
        "--alias",
        help="Alias do tribunal no DataJud (ex.: tjsp); inferido do número se omitido.",
    )
    andamentos_parser.add_argument("--limit", type=int, default=20)

    portal_parser = subparsers.add_parser(
        "portal",
        help="Consultar o teor do processo no portal do tribunal (e-SAJ, autenticado)",
    )
    portal_parser.add_argument("--numero", required=True, help="Número do processo (CNJ).")
    portal_parser.add_argument(
        "--tribunal",
        help="Sigla do tribunal (ex.: TJSP); inferida do número se omitida.",
    )
    portal_parser.add_argument(
        "--headed",
        action="store_true",
        help="Abre o navegador com interface (para resolver captcha/2FA manualmente).",
    )
    portal_parser.add_argument(
        "--autenticado",
        action="store_true",
        help="Pula a consulta pública e vai direto ao login (útil para segredo de justiça).",
    )
    portal_parser.add_argument(
        "--token-email",
        action="store_true",
        help="Lê o código 2FA do e-SAJ na caixa Gmail autorizada (se o código chegar lá).",
    )
    portal_parser.add_argument(
        "--token-code",
        help="Informa manualmente o código 2FA enviado ao e-mail cadastrado.",
    )

    boards_parser = subparsers.add_parser(
        "boards",
        help="Listar boards do Monday com grupos, colunas e mapeamento detectado",
    )
    boards_parser.add_argument(
        "--filter",
        help="Filtra boards pelo nome (ex.: prazos, audiencias, processos).",
    )

    events_parser = subparsers.add_parser(
        "events",
        help="Listar eventos de handoff para os agentes futuros",
    )
    events_parser.add_argument(
        "--type",
        choices=("elaborar_peca", "atualizar_contingencia"),
        help="Filtrar por tipo de evento.",
    )
    events_parser.add_argument(
        "--events-path",
        default="data/juridico-events.jsonl",
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args(argv)

    if args.command == "list":
        return _run_list(args)
    if args.command == "process":
        return _run_process(args)
    if args.command == "comunicacoes":
        return _run_comunicacoes(args)
    if args.command == "andamentos":
        return _run_andamentos(args)
    if args.command == "portal":
        return _run_portal(args)
    if args.command == "boards":
        return _run_boards(args)
    if args.command == "events":
        return _run_events(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
