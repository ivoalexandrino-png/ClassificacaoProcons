"""CLI do Radar de editais: lista fontes, analisa snapshots e envia o digest."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from classificacao_procons.radar.analise import analyze_snapshot
from classificacao_procons.radar.models import CORE_AREAS, Area, Scope
from classificacao_procons.radar.pipeline import (
    RadarPipelineError,
    RadarPipelineOptions,
    run_radar_check,
)
from classificacao_procons.radar.serialization import (
    SnapshotParseError,
    analysis_to_dict,
    snapshot_from_dict,
)
from classificacao_procons.radar.sources import get_sources

_VALID_AREAS: tuple[Area, ...] = CORE_AREAS


def _default_token_path() -> str:
    return os.environ.get("GMAIL_TOKEN_PATH", "credentials/gmail-token.json")


def _split_list(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    parts = re.split(r"[,;\s]+", value.strip())
    return tuple(part for part in parts if part)


def _parse_areas(value: str | None) -> tuple[Area, ...]:
    if not value:
        return CORE_AREAS
    requested = _split_list(value.casefold())
    areas = tuple(area for area in _VALID_AREAS if area in requested)
    return areas or CORE_AREAS


def _parse_scope(value: str | None) -> Scope | None:
    if not value:
        return None
    text = value.strip().casefold()
    if text in ("nacional", "internacional"):
        return text  # type: ignore[return-value]
    return None


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


def _run_sources(args: argparse.Namespace) -> int:
    sources = get_sources(scope=_parse_scope(args.scope), area=_parse_areas_single(args.area))
    payload = [
        {
            "key": source.key,
            "name": source.name,
            "scope": source.scope,
            "areas": list(source.areas),
            "url": source.url,
        }
        for source in sources
    ]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _parse_areas_single(value: str | None) -> Area | None:
    if not value:
        return None
    text = value.strip().casefold()
    return text if text in _VALID_AREAS else None  # type: ignore[return-value]


def _run_scan(args: argparse.Namespace) -> int:
    try:
        snapshot = _load_snapshot_file(args.snapshot)
    except SnapshotParseError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    analysis = analyze_snapshot(
        snapshot,
        interest_areas=_parse_areas(args.areas),
        include_closed=args.include_closed,
    )
    print(json.dumps(analysis_to_dict(analysis), ensure_ascii=False, indent=2))
    return 0


def _run_check(args: argparse.Namespace) -> int:
    options = RadarPipelineOptions(
        recipients=_split_list(args.to),
        cc=_split_list(args.cc),
        sender=args.sender,
        interest_areas=_parse_areas(args.areas),
        scope=_parse_scope(args.scope),
        source_keys=_split_list(args.sources) or None,
        include_closed=args.include_closed,
        dry_run=args.dry_run,
        only_new=not args.resend,
        state_path=Path(args.state_path),
        token_path=args.token,
    )

    snapshot = None
    if args.snapshot:
        try:
            snapshot = _load_snapshot_file(args.snapshot)
        except SnapshotParseError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 1

    try:
        result = run_radar_check(options, snapshot=snapshot)
    except RadarPipelineError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    payload = {
        "status": result.status,
        "alert_sent": result.alert_sent,
        "alert_recipients": list(result.alert_recipients),
        "message_id": result.message_id,
        "new_match_count": len(result.new_matches),
    }
    if result.analysis is not None:
        payload["match_count"] = len(result.analysis.matches)
        payload["open_count"] = len(result.analysis.open_matches)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _add_area_scope_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--areas",
        help="Áreas de interesse (direito,saude,administracao,educacao). Padrão: todas.",
    )
    parser.add_argument(
        "--scope",
        help="Filtra a abrangência: nacional ou internacional (padrão: ambas).",
    )
    parser.add_argument(
        "--include-closed",
        action="store_true",
        help="Inclui também editais encerrados (padrão: só aproveitáveis).",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Radar de editais — monitora fontes de fomento nacionais e internacionais "
            "(Direito, Saúde, Administração, Educação) e avisa os pesquisadores por e-mail "
            "quando surgem editais/chamadas relevantes."
        ),
    )
    parser.add_argument("--token", default=_default_token_path(), help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command")

    sources_parser = subparsers.add_parser(
        "sources",
        help="Lista as fontes de fomento monitoradas (com filtros).",
    )
    sources_parser.add_argument("--scope", help="nacional ou internacional.")
    sources_parser.add_argument(
        "--area",
        help="Filtra por uma área (direito/saude/administracao/educacao).",
    )

    scan_parser = subparsers.add_parser(
        "scan",
        help="Analisa um snapshot (JSON) offline e lista os editais relevantes.",
    )
    scan_parser.add_argument(
        "--snapshot",
        required=True,
        help="Arquivo JSON com os editais coletados.",
    )
    _add_area_scope_args(scan_parser)

    check_parser = subparsers.add_parser(
        "check",
        help="Coleta (fontes ou snapshot), analisa e envia o digest por e-mail.",
    )
    check_parser.add_argument("--to", help="Destinatários do digest, separados por vírgula.")
    check_parser.add_argument("--cc", help="Cópia (CC), separados por vírgula.")
    check_parser.add_argument("--sender", help="Remetente (From) do e-mail.")
    _add_area_scope_args(check_parser)
    check_parser.add_argument(
        "--sources",
        help="Restringe às chaves de fonte informadas (ex.: cnpq,capes,nih).",
    )
    check_parser.add_argument(
        "--snapshot",
        help="Usa um snapshot JSON em vez de acessar as fontes (não requer rede).",
    )
    check_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra os editais que seriam enviados, sem enviar e-mail.",
    )
    check_parser.add_argument(
        "--resend",
        action="store_true",
        help="Reenvia todos os editais, ignorando o estado de já avisados.",
    )
    check_parser.add_argument(
        "--state-path",
        default="data/radar-alerted.json",
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args(argv)

    if args.command == "sources":
        return _run_sources(args)
    if args.command == "scan":
        return _run_scan(args)
    if args.command == "check":
        return _run_check(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
