"""Fluxo automático do agente jurídico: intimação → andamento → Monday."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from classificacao_procons.email import GmailClientError
from classificacao_procons.google_auth import has_gmail_modify_access, has_valid_token
from classificacao_procons.juridico.agents import (
    NullPecaProcessualAgent,
    NullRelatorioContingenciaAgent,
    PecaProcessualAgent,
    RelatorioContingenciaAgent,
)
from classificacao_procons.juridico.andamento import AndamentoSource, EmailAndamentoSource
from classificacao_procons.juridico.gmail import GmailIntimacaoFetcher
from classificacao_procons.juridico.models import (
    IntimacaoEmail,
    ProcessoJudicial,
    Providencia,
    RegistroJuridicoResult,
)
from classificacao_procons.juridico.monday_juridico import (
    ProvidenciaRegistrationResult,
    get_api_token_from_env,
    register_providencia,
)
from classificacao_procons.juridico.providencia import classify_providencia
from classificacao_procons.monday.client import MondayClientError

DEFAULT_STATE_PATH = Path("data/processed-intimacoes.json")


class JuridicoPipelineError(RuntimeError):
    """Erro geral no pipeline do agente jurídico."""


@dataclass(frozen=True)
class JuridicoPipelineOptions:
    max_results: int = 20
    state_path: Path = DEFAULT_STATE_PATH
    mark_read: bool = True
    dry_run: bool = False
    credentials_path: str = "credentials/gmail-oauth.json"
    token_path: str = "credentials/gmail-token.json"
    monday_api_token: str | None = None
    monday_board_name: str | None = None
    monday_group_name: str | None = None
    monday_board_id: str | None = None
    register_on_monday: bool = True
    holidays: frozenset[date] = field(default_factory=frozenset)


def _load_processed_keys(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(item) for item in data.get("keys", [])}


def _save_processed_keys(state_path: Path, keys: set[str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"keys": sorted(keys)}
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _dedup_key(intimacao: IntimacaoEmail) -> str:
    parts = [
        intimacao.process_number or intimacao.message_id,
        intimacao.movement_type or "",
        intimacao.publication_date.isoformat() if intimacao.publication_date else "",
        intimacao.hearing_at.isoformat() if intimacao.hearing_at else "",
    ]
    return "|".join(parts)


def _resolve_monday_api_token(options: JuridicoPipelineOptions) -> str | None:
    if options.monday_api_token:
        return options.monday_api_token
    return get_api_token_from_env()


def _build_processo(intimacao: IntimacaoEmail, source: AndamentoSource) -> ProcessoJudicial:
    andamentos = tuple(source.fetch_andamentos(intimacao))
    return ProcessoJudicial(
        process_number=intimacao.process_number or "",
        tribunal=intimacao.tribunal,
        vara=intimacao.vara,
        parties=intimacao.parties,
        portal_url=intimacao.portal_url,
        andamentos=andamentos,
    )


def _process_intimacao(
    intimacao: IntimacaoEmail,
    *,
    options: JuridicoPipelineOptions,
    processed_keys: set[str],
    fetcher: GmailIntimacaoFetcher,
    andamento_source: AndamentoSource,
    peca_agent: PecaProcessualAgent,
    relatorio_agent: RelatorioContingenciaAgent,
) -> RegistroJuridicoResult:
    if options.dry_run:
        providencia = classify_providencia(intimacao, holidays=options.holidays)
        return RegistroJuridicoResult(
            status="dry_run",
            message_id=intimacao.message_id,
            process_number=intimacao.process_number or "",
            tipo=providencia.tipo,
            descricao=providencia.descricao,
            prazo_final=providencia.prazo_final,
            hearing_at=providencia.hearing_at,
            tribunal=intimacao.tribunal,
            vara=intimacao.vara,
        )

    key = _dedup_key(intimacao)
    if key in processed_keys:
        return RegistroJuridicoResult(
            status="skipped_duplicate",
            message_id=intimacao.message_id,
            process_number=intimacao.process_number or "",
            tipo=intimacao.movement_type or "",
            descricao="Intimação já processada anteriormente.",
            tribunal=intimacao.tribunal,
            vara=intimacao.vara,
        )

    processo = _build_processo(intimacao, andamento_source)
    providencia = classify_providencia(intimacao, holidays=options.holidays)

    result = RegistroJuridicoResult(
        status="success",
        message_id=intimacao.message_id,
        process_number=providencia.process_number,
        tipo=providencia.tipo,
        descricao=providencia.descricao,
        prazo_final=providencia.prazo_final,
        hearing_at=providencia.hearing_at,
        tribunal=intimacao.tribunal,
        vara=intimacao.vara,
    )

    # Relatório contingencial: sempre atualizado com o andamento mais recente.
    if processo.andamentos:
        relatorio = relatorio_agent.update_report(processo, processo.andamentos[-1])
        result = replace(result, relatorio_status=relatorio.status)

    if providencia.requires_action:
        result = _register_on_monday_if_configured(result, providencia, processo, options=options)
        peca = peca_agent.draft_and_file(processo, providencia)
        result = replace(result, peca_status=peca.status)
    else:
        result = replace(result, status="acompanhar")

    processed_keys.add(key)
    _save_processed_keys(options.state_path, processed_keys)

    if options.mark_read and has_gmail_modify_access(options.token_path):
        fetcher.mark_as_read(intimacao.message_id)

    return result


def _register_on_monday_if_configured(
    result: RegistroJuridicoResult,
    providencia: Providencia,
    processo: ProcessoJudicial,
    *,
    options: JuridicoPipelineOptions,
) -> RegistroJuridicoResult:
    if not options.register_on_monday:
        return result

    api_token = _resolve_monday_api_token(options)
    if not api_token:
        return result

    try:
        monday_result: ProvidenciaRegistrationResult | None = register_providencia(
            providencia,
            processo,
            api_token=api_token,
            board_name=options.monday_board_name,
            group_name=options.monday_group_name,
            board_id=options.monday_board_id,
        )
    except MondayClientError as exc:
        return replace(result, monday_error=str(exc))

    if monday_result is None:
        return result
    return replace(result, monday_item_url=monday_result.item_url)


def process_new_intimacoes(
    options: JuridicoPipelineOptions | None = None,
    *,
    andamento_source: AndamentoSource | None = None,
    peca_agent: PecaProcessualAgent | None = None,
    relatorio_agent: RelatorioContingenciaAgent | None = None,
) -> list[RegistroJuridicoResult]:
    """Processa intimações não lidas: andamento → providência → Monday.

    Os agentes futuros (peças e relatórios contingenciais) e a fonte de
    andamento são injetáveis; por padrão usa a fonte de e-mail e os agentes
    nulos (no-op), que sinalizam "pendente_integracao".
    """
    options = options or JuridicoPipelineOptions()
    andamento_source = andamento_source or EmailAndamentoSource()
    peca_agent = peca_agent or NullPecaProcessualAgent()
    relatorio_agent = relatorio_agent or NullRelatorioContingenciaAgent()

    if not options.dry_run and not has_valid_token(options.token_path):
        raise JuridicoPipelineError("Google não conectado. Rode: procon-juridico auth")

    fetcher = GmailIntimacaoFetcher.from_credentials(
        credentials_path=options.credentials_path,
        token_path=options.token_path,
    )

    try:
        intimacoes = fetcher.list_unread_intimacoes(max_results=options.max_results)
    except GmailClientError as exc:
        raise JuridicoPipelineError(str(exc)) from exc

    processed_keys = _load_processed_keys(options.state_path)
    results: list[RegistroJuridicoResult] = []
    for intimacao in intimacoes:
        try:
            result = _process_intimacao(
                intimacao,
                options=options,
                processed_keys=processed_keys,
                fetcher=fetcher,
                andamento_source=andamento_source,
                peca_agent=peca_agent,
                relatorio_agent=relatorio_agent,
            )
        except (MondayClientError, GmailClientError) as exc:
            result = RegistroJuridicoResult(
                status="error",
                message_id=intimacao.message_id,
                process_number=intimacao.process_number or "",
                tipo=intimacao.movement_type or "",
                descricao="",
                tribunal=intimacao.tribunal,
                vara=intimacao.vara,
                error=str(exc),
            )
        results.append(result)

    return results
