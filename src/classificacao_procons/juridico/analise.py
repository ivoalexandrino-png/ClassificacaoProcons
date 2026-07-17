"""Análise caso a caso: entender o que aconteceu antes de cadastrar no Monday.

Com ``GEMINI_API_KEY`` configurada, a análise é gerada pelo Gemini a partir da
intimação, do teor das comunicações (Domicílio Judicial Eletrônico) e dos
andamentos (DataJud). Sem a chave — ou se o Gemini falhar — cai para um resumo
heurístico estruturado, para o fluxo nunca ficar bloqueado.
"""

from __future__ import annotations

from classificacao_procons.gemini.client import (
    GeminiClientError,
    _gemini_request,
    get_api_key_from_env,
    get_model_from_env,
    list_generate_content_models,
    resolve_gemini_model,
)
from classificacao_procons.juridico.models import (
    CaseAnalysis,
    CaseCommunication,
    CaseMovement,
    ParsedIntimacao,
    Providencia,
)

ANALYSIS_SOURCE_GEMINI = "gemini"
ANALYSIS_SOURCE_HEURISTIC = "heuristica"

_MAX_COMMUNICATION_CHARS = 4000
_MAX_MOVEMENTS_IN_PROMPT = 10


def _format_communications(communications: list[CaseCommunication]) -> str:
    if not communications:
        return "(nenhuma comunicação encontrada)"
    blocks: list[str] = []
    for communication in communications:
        header_parts = [
            part
            for part in (
                communication.communication_type,
                communication.organ,
                communication.available_date,
            )
            if part
        ]
        header = " — ".join(header_parts) or "Comunicação"
        blocks.append(f"[{header}]\n{communication.text[:_MAX_COMMUNICATION_CHARS]}")
    return "\n\n".join(blocks)


def _format_movements(movements: list[CaseMovement]) -> str:
    if not movements:
        return "(nenhum andamento disponível)"
    lines: list[str] = []
    for movement in movements[:_MAX_MOVEMENTS_IN_PROMPT]:
        moment = (
            movement.movement_datetime.date().isoformat()
            if movement.movement_datetime
            else "s/ data"
        )
        lines.append(f"- {moment}: {movement.movement_name}")
    return "\n".join(lines)


def build_heuristic_analysis(
    *,
    intimacao: ParsedIntimacao,
    providencia: Providencia,
    communications: list[CaseCommunication],
    movements: list[CaseMovement],
) -> CaseAnalysis:
    """Resumo estruturado sem IA: o que chegou, o que o processo mostra, o que fazer."""
    location = " — ".join(part for part in (intimacao.tribunal, intimacao.court_unit) if part)
    due = providencia.due_date.isoformat() if providencia.due_date else "sem prazo identificado"
    hearing = (
        providencia.hearing_datetime.strftime("%d/%m/%Y %H:%M")
        if providencia.hearing_datetime
        else None
    )

    lines = [
        f"Processo {intimacao.process_number}" + (f" ({location})" if location else ""),
        f"O que chegou: {intimacao.notification_type} — {intimacao.summary[:300]}",
        f"Teor no Domicílio Judicial: {_format_communications(communications)[:600]}",
        f"Últimos andamentos: {_format_movements(movements)[:600]}",
        f"Providência sugerida: {providencia.description} (prazo fatal: {due}).",
    ]
    if hearing:
        lines.append(f"Audiência: {hearing}.")
    lines.append("Análise heurística — revisar antes de dar andamento.")
    return CaseAnalysis(text="\n".join(lines), source=ANALYSIS_SOURCE_HEURISTIC)


def _build_gemini_prompt(
    *,
    intimacao: ParsedIntimacao,
    providencia: Providencia,
    communications: list[CaseCommunication],
    movements: list[CaseMovement],
) -> str:
    due = providencia.due_date.isoformat() if providencia.due_date else "não identificado"
    return (
        "Você é advogado(a) interno(a) da empresa (polo passivo). Analise a intimação "
        "abaixo junto com o teor das comunicações do Domicílio Judicial Eletrônico e os "
        "últimos andamentos do processo, e produza um parecer curto para o quadro de "
        "controle de prazos:\n"
        "1) O QUE ACONTECEU (2-3 frases, em linguagem direta);\n"
        "2) PROVIDÊNCIA (o que a empresa precisa fazer e até quando);\n"
        "3) PONTOS DE ATENÇÃO (riscos, valores, depósitos, audiências).\n"
        "Não invente fatos; se a informação não estiver nos textos, diga que não consta.\n"
        "Responda em português do Brasil, sem markdown, no máximo 200 palavras.\n\n"
        f"PROCESSO: {intimacao.process_number} "
        f"({intimacao.tribunal or 'tribunal não identificado'})\n"
        f"VARA/ÓRGÃO: {intimacao.court_unit or 'não identificado'}\n"
        f"TRIAGEM AUTOMÁTICA: {providencia.description} — prazo fatal {due}\n\n"
        f"E-MAIL/INTIMAÇÃO RECEBIDA:\n{intimacao.summary}\n\n"
        f"TEOR DAS COMUNICAÇÕES (Domicílio Judicial Eletrônico):\n"
        f"{_format_communications(communications)}\n\n"
        f"ÚLTIMOS ANDAMENTOS (DataJud):\n{_format_movements(movements)}"
    )


def analyze_case(
    *,
    intimacao: ParsedIntimacao,
    providencia: Providencia,
    communications: list[CaseCommunication],
    movements: list[CaseMovement],
    api_key: str | None = None,
) -> CaseAnalysis:
    """Gera o entendimento do caso (Gemini quando disponível, senão heurística)."""
    key = api_key or get_api_key_from_env()
    if not key:
        return build_heuristic_analysis(
            intimacao=intimacao,
            providencia=providencia,
            communications=communications,
            movements=movements,
        )

    try:
        model = resolve_gemini_model(
            available_models=list_generate_content_models(api_key=key),
            preferred=get_model_from_env(),
        )
        text = _gemini_request(
            api_key=key,
            model=model,
            parts=[
                {
                    "text": _build_gemini_prompt(
                        intimacao=intimacao,
                        providencia=providencia,
                        communications=communications,
                        movements=movements,
                    ),
                },
            ],
        )
    except GeminiClientError:
        return build_heuristic_analysis(
            intimacao=intimacao,
            providencia=providencia,
            communications=communications,
            movements=movements,
        )

    return CaseAnalysis(text=text.strip(), source=ANALYSIS_SOURCE_GEMINI)
