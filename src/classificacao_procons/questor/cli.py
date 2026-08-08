"""CLI do agente Questor: análise de certidões/caixa postal e alerta fiscal."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from classificacao_procons.questor.analise import DEFAULT_WARN_WITHIN_DAYS, analyze_snapshot
from classificacao_procons.questor.pipeline import (
    QuestorPipelineError,
    QuestorPipelineOptions,
    run_questor_check,
)
from classificacao_procons.questor.serialization import (
    SnapshotParseError,
    analysis_to_dict,
    snapshot_from_dict,
)


def _default_token_path() -> str:
    return os.environ.get("GMAIL_TOKEN_PATH", "credentials/gmail-token.json")


def _split_recipients(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    parts = re.split(r"[,;\s]+", value.strip())
    return tuple(part for part in parts if part)


def _load_snapshot_file(path: str):
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise SnapshotParseError(f"Não foi possível ler o arquivo: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SnapshotParseError(f"JSON inválido: {exc}") from exc
    return snapshot_from_dict(data)


def _run_analyze(args: argparse.Namespace) -> int:
    try:
        snapshot = _load_snapshot_file(args.snapshot)
    except SnapshotParseError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    analysis = analyze_snapshot(snapshot, warn_within_days=args.warn_within_days)
    print(json.dumps(analysis_to_dict(analysis), ensure_ascii=False, indent=2))
    return 1 if analysis.critical_issues else 0


def _run_check(args: argparse.Namespace) -> int:
    recipients = _split_recipients(args.to)
    cc = _split_recipients(args.cc)
    options = QuestorPipelineOptions(
        recipients=recipients,
        cc=cc,
        sender=args.sender,
        warn_within_days=args.warn_within_days,
        dry_run=args.dry_run,
        only_new=not args.resend,
        state_path=Path(args.state_path),
        token_path=args.token,
        portal_url=args.portal_url or os.environ.get("QUESTOR_PORTAL_URL"),
        portal_login=args.portal_login or os.environ.get("QUESTOR_LOGIN"),
        portal_password=args.portal_password or os.environ.get("QUESTOR_PASSWORD"),
        empresa=args.empresa,
        cnpj=args.cnpj,
        headless=not args.headed,
    )

    snapshot = None
    if args.snapshot:
        try:
            snapshot = _load_snapshot_file(args.snapshot)
        except SnapshotParseError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 1

    try:
        result = run_questor_check(options, snapshot=snapshot)
    except QuestorPipelineError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    payload = {
        "status": result.status,
        "alert_sent": result.alert_sent,
        "alert_recipients": list(result.alert_recipients),
        "message_id": result.message_id,
        "new_issue_count": len(result.new_issues),
    }
    if result.analysis is not None:
        payload["analysis"] = analysis_to_dict(result.analysis)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Agente Questor — analisa certidões negativas e a caixa postal fiscal, "
            "e alerta o time fiscal/contábil por e-mail quando há pendência."
        ),
    )
    parser.add_argument("--token", default=_default_token_path(), help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command")

    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analisar um snapshot (JSON) offline e listar as pendências.",
    )
    analyze_parser.add_argument(
        "--snapshot",
        required=True,
        help="Arquivo JSON com certidões e mensagens da caixa postal.",
    )
    analyze_parser.add_argument(
        "--warn-within-days",
        type=int,
        default=DEFAULT_WARN_WITHIN_DAYS,
        help="Janela (dias) para avisar certidão/prazo a vencer.",
    )

    check_parser = subparsers.add_parser(
        "check",
        help="Coletar (portal ou snapshot), analisar e alertar o time por e-mail.",
    )
    check_parser.add_argument(
        "--to",
        help="Destinatários do alerta (fiscal/contabilidade), separados por vírgula.",
    )
    check_parser.add_argument("--cc", help="Cópia (CC) do alerta, separados por vírgula.")
    check_parser.add_argument("--sender", help="Remetente (From) do e-mail.")
    check_parser.add_argument(
        "--snapshot",
        help="Usa um snapshot JSON em vez de acessar o portal (não requer Playwright).",
    )
    check_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra as pendências que seriam enviadas, sem enviar e-mail.",
    )
    check_parser.add_argument(
        "--resend",
        action="store_true",
        help="Reenvia todas as pendências, ignorando o estado de já alertadas.",
    )
    check_parser.add_argument(
        "--warn-within-days",
        type=int,
        default=DEFAULT_WARN_WITHIN_DAYS,
    )
    check_parser.add_argument(
        "--state-path",
        default="data/questor-alerted.json",
        help=argparse.SUPPRESS,
    )
    check_parser.add_argument("--portal-url", help="URL de login do Questor.")
    check_parser.add_argument("--portal-login", help="Usuário do Questor.")
    check_parser.add_argument("--portal-password", help="Senha do Questor.")
    check_parser.add_argument("--empresa", help="Nome da empresa (rótulo no alerta).")
    check_parser.add_argument("--cnpj", help="CNPJ da empresa.")
    check_parser.add_argument(
        "--headed",
        action="store_true",
        help="Abre o navegador com interface (para resolver captcha/2FA).",
    )

    args = parser.parse_args(argv)

    if args.command == "analyze":
        return _run_analyze(args)
    if args.command == "check":
        return _run_check(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
