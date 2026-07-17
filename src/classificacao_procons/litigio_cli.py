"""CLI do agente de monitoramento de litígio (intimações → providência → Monday)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from classificacao_procons.litigio.models import EventoProcesso
from classificacao_procons.litigio.parser import analisar_texto_bruto
from classificacao_procons.litigio.pipeline import (
    LitigioPipelineError,
    LitigioPipelineOptions,
    monitorar_intimacoes,
)


def _default_numero_oab() -> str:
    return os.environ.get("DJEN_NUMERO_OAB", "")


def _default_uf_oab() -> str:
    return os.environ.get("DJEN_UF_OAB", "")


def _parse_date_arg(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _serialize_evento(evento: EventoProcesso) -> dict[str, object]:
    data = asdict(evento)
    data["tipo_providencia"] = evento.tipo_providencia.value
    for key in ("data_disponibilizacao", "prazo_data", "data_audiencia"):
        if data.get(key) is not None:
            data[key] = data[key].isoformat()
    return data


def _run_monitor(args: argparse.Namespace) -> int:
    options = LitigioPipelineOptions(
        numero_oab=args.numero_oab,
        uf_oab=args.uf_oab,
        data_inicio=_parse_date_arg(args.data_inicio),
        data_fim=_parse_date_arg(args.data_fim),
        numero_processo=args.numero_processo,
        sigla_tribunal=args.tribunal,
        state_path=Path(args.state_path),
        eventos_log_path=Path(args.eventos_log_path),
        dry_run=args.dry_run,
    )

    try:
        eventos = monitorar_intimacoes(options)
    except LitigioPipelineError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    output = [_serialize_evento(evento) for evento in eventos]
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if any(evento.monday_error for evento in eventos):
        return 1
    return 0


def _run_parse(args: argparse.Namespace) -> int:
    texto = Path(args.arquivo).read_text(encoding="utf-8") if args.arquivo else sys.stdin.read()

    providencia = analisar_texto_bruto(
        texto=texto,
        tipo_documento=args.tipo_documento,
        numero_processo=args.numero_processo or "",
    )

    data = asdict(providencia)
    data["tipo"] = providencia.tipo.value
    if data.get("prazo_data"):
        data["prazo_data"] = data["prazo_data"].isoformat()
    if data.get("data_audiencia"):
        data["data_audiencia"] = data["data_audiencia"].isoformat()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Agente de litígio — monitora intimações do DJEN, classifica "
            "providências (prazo/audiência) e sincroniza o Monday."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    monitor_parser = subparsers.add_parser(
        "monitor",
        help="Consultar DJEN por OAB e sincronizar providências no Monday",
    )
    monitor_parser.add_argument("--numero-oab", default=_default_numero_oab())
    monitor_parser.add_argument("--uf-oab", default=_default_uf_oab())
    monitor_parser.add_argument("--data-inicio", help="AAAA-MM-DD (padrão: ontem)")
    monitor_parser.add_argument("--data-fim", help="AAAA-MM-DD (padrão: hoje)")
    monitor_parser.add_argument("--numero-processo", help="Filtrar por um único processo")
    monitor_parser.add_argument("--tribunal", help="Sigla do tribunal (ex.: TJSP)")
    monitor_parser.add_argument(
        "--state-path",
        default=str(LitigioPipelineOptions.state_path),
    )
    monitor_parser.add_argument(
        "--eventos-log-path",
        default=str(LitigioPipelineOptions.eventos_log_path),
    )
    monitor_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Só lista as intimações novas, sem gravar estado nem Monday.",
    )

    parse_parser = subparsers.add_parser(
        "parse",
        help="Analisar um texto de intimação isolado (sem DJEN)",
    )
    parse_parser.add_argument(
        "--arquivo",
        help="Caminho do arquivo com o texto; se omitido, lê da entrada padrão.",
    )
    parse_parser.add_argument("--tipo-documento", default="", help="Ex.: Despacho, Sentença")
    parse_parser.add_argument("--numero-processo", help="Número do processo (opcional)")

    args = parser.parse_args(argv)

    if args.command == "monitor":
        if not args.numero_oab or not args.uf_oab:
            print(
                "--numero-oab e --uf-oab são obrigatórios "
                "(ou DJEN_NUMERO_OAB/DJEN_UF_OAB no ambiente).",
                file=sys.stderr,
            )
            return 1
        return _run_monitor(args)
    if args.command == "parse":
        return _run_parse(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
