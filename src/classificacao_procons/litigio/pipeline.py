"""Fluxo automático: DJEN → análise de providência → Monday → eventos."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

from classificacao_procons.litigio.djen_client import DjenClientError, DjenQueryOptions
from classificacao_procons.litigio.djen_client import consultar_intimacoes as _consultar_djen
from classificacao_procons.litigio.hooks import notificar_handlers
from classificacao_procons.litigio.models import EventoProcesso, Intimacao
from classificacao_procons.litigio.monday_litigio import (
    MondayClientError,
    get_litigio_board_name_from_env,
    get_litigio_group_name_from_env,
    register_or_update_processo,
)
from classificacao_procons.litigio.parser import analisar_intimacao

DEFAULT_STATE_PATH = Path("data/litigio-intimacoes-processadas.json")
DEFAULT_EVENTOS_LOG_PATH = Path("data/litigio-eventos.jsonl")
DEFAULT_JANELA_DIAS = 2  # ontem + hoje: tolera atraso de disponibilização no DJEN


class LitigioPipelineError(RuntimeError):
    """Erro geral no pipeline de monitoramento de litígio."""


@dataclass(frozen=True)
class LitigioPipelineOptions:
    numero_oab: str
    uf_oab: str
    data_inicio: date | None = None
    data_fim: date | None = None
    numero_processo: str | None = None
    sigla_tribunal: str | None = None
    state_path: Path = DEFAULT_STATE_PATH
    eventos_log_path: Path = DEFAULT_EVENTOS_LOG_PATH
    monday_api_token: str | None = None
    monday_board_name: str | None = None
    monday_group_name: str | None = None
    monday_board_id: str | None = None
    register_on_monday: bool = True
    dry_run: bool = False


def _resolve_janela(options: LitigioPipelineOptions) -> tuple[date, date]:
    fim = options.data_fim or date.today()
    inicio = options.data_inicio or (fim - timedelta(days=DEFAULT_JANELA_DIAS - 1))
    return inicio, fim


def _load_processed_ids(state_path: Path) -> set[int]:
    if not state_path.exists():
        return set()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids = data.get("intimacao_ids", [])
    return {int(item) for item in ids}


def _save_processed_ids(state_path: Path, ids: set[int]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"intimacao_ids": sorted(ids)}
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_evento_log(log_path: Path, evento: EventoProcesso) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "numero_processo": evento.numero_processo,
        "numero_processo_formatado": evento.numero_processo_formatado,
        "tribunal": evento.tribunal,
        "tipo_providencia": evento.tipo_providencia.value,
        "descricao": evento.descricao,
        "requer_atencao": evento.requer_atencao,
        "intimacao_id": evento.intimacao_id,
        "data_disponibilizacao": evento.data_disponibilizacao.isoformat(),
        "prazo_data": evento.prazo_data.isoformat() if evento.prazo_data else None,
        "data_audiencia": evento.data_audiencia.isoformat() if evento.data_audiencia else None,
        "certidao_url": evento.certidao_url,
        "link_tribunal": evento.link_tribunal,
        "monday_item_url": evento.monday_item_url,
        "monday_error": evento.monday_error,
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _register_on_monday_if_configured(
    evento: EventoProcesso,
    *,
    options: LitigioPipelineOptions,
) -> EventoProcesso:
    if not options.register_on_monday or not evento.requer_atencao:
        return evento

    try:
        resultado = register_or_update_processo(
            evento,
            api_token=options.monday_api_token,
            board_name=options.monday_board_name or get_litigio_board_name_from_env(),
            group_name=options.monday_group_name or get_litigio_group_name_from_env(),
            board_id=options.monday_board_id,
        )
    except MondayClientError as exc:
        return replace(evento, monday_error=str(exc))

    if resultado is None:
        return evento
    return replace(evento, monday_item_url=resultado.item_url)


def _build_evento(intimacao: Intimacao) -> EventoProcesso:
    providencia = analisar_intimacao(intimacao)
    return EventoProcesso(
        numero_processo=intimacao.numero_processo,
        numero_processo_formatado=intimacao.numero_processo_formatado,
        tribunal=intimacao.tribunal,
        tipo_providencia=providencia.tipo,
        descricao=providencia.descricao,
        requer_atencao=providencia.requer_atencao,
        intimacao_id=intimacao.id,
        data_disponibilizacao=intimacao.data_disponibilizacao,
        prazo_data=providencia.prazo_data,
        data_audiencia=providencia.data_audiencia,
        certidao_url=intimacao.certidao_url,
        link_tribunal=intimacao.link,
    )


def monitorar_intimacoes(options: LitigioPipelineOptions) -> list[EventoProcesso]:
    """Consulta o DJEN, classifica providências novas e sincroniza o Monday."""
    if not options.numero_oab or not options.uf_oab:
        raise LitigioPipelineError("numero_oab e uf_oab são obrigatórios.")

    data_inicio, data_fim = _resolve_janela(options)

    try:
        intimacoes = _consultar_djen(
            DjenQueryOptions(
                data_inicio=data_inicio,
                data_fim=data_fim,
                numero_oab=options.numero_oab,
                uf_oab=options.uf_oab,
                numero_processo=options.numero_processo,
                sigla_tribunal=options.sigla_tribunal,
            ),
        )
    except DjenClientError as exc:
        raise LitigioPipelineError(str(exc)) from exc

    processed_ids = _load_processed_ids(options.state_path)
    novas_intimacoes = [item for item in intimacoes if item.id not in processed_ids]

    eventos: list[EventoProcesso] = []
    for intimacao in novas_intimacoes:
        evento = _build_evento(intimacao)

        if not options.dry_run:
            evento = _register_on_monday_if_configured(evento, options=options)
            _append_evento_log(options.eventos_log_path, evento)
            notificar_handlers(evento)
            processed_ids.add(intimacao.id)

        eventos.append(evento)

    if not options.dry_run and novas_intimacoes:
        _save_processed_ids(options.state_path, processed_ids)

    return eventos
