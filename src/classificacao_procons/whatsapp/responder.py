"""Planejamento de respostas automáticas com política de risco."""

from __future__ import annotations

from dataclasses import dataclass

from classificacao_procons.whatsapp.history import format_history_for_prompt
from classificacao_procons.whatsapp.llm import (
    LlmReplyResult,
    WhatsappLlmError,
    generate_whatsapp_reply,
)
from classificacao_procons.whatsapp.models import ConversationThread, IncomingMessage, ReplyPlan
from classificacao_procons.whatsapp.risk import heuristic_risk_tier

DEFAULT_PERSONA = (
    "Você responde WhatsApp em nome do usuário, de forma natural em português do Brasil, "
    "concisa e cordial, misturando tom pessoal e profissional conforme o contexto."
)

LEGAL_HOLD_TEMPLATE = (
    "Oi! Recebi sua mensagem sobre esse assunto. Por cautela, prefiro analisar com calma "
    "antes de me comprometer por aqui — te retorno em breve, ok?"
)


@dataclass(frozen=True)
class ResponderOptions:
    owner_name: str = "eu"
    persona: str = DEFAULT_PERSONA
    gemini_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_model: str | None = None
    openai_model: str | None = None


def _system_prompt(options: ResponderOptions) -> str:
    return f"""Você é o assistente de respostas automáticas no WhatsApp de {options.owner_name}.
{options.persona}

Regras obrigatórias:
1. Responda SEMPRE em JSON válido, sem markdown, no formato:
   {{"tier":"routine|ambiguous|legal_high","reply":"texto","reasons":["motivo curto"]}}
2. tier=routine: assuntos cotidianos, agendamentos, confirmações, cordialidades.
3. tier=ambiguous: falta contexto, pedidos vagos, múltiplas interpretações — peça UMA clarificação
   objetiva, usando o histórico quando existir.
4. tier=legal_high: processos, contratos, Procon, trabalhista, fiscal, multas, prazos legais,
   confidencialidade contratual, compromissos que gerem obrigação — NÃO dê orientação jurídica,
   NÃO confirme fatos sensíveis, NÃO aceite termos. Use tom empático e diga que vai analisar
   e retornar em breve (sem inventar prazos específicos).
5. Use o histórico do chat para manter coerência; não repita informações já ditas.
6. Mensagem final (campo reply): só o texto enviado no WhatsApp, sem aspas extras,
   máx. ~900 caracteres.
7. Nunca diga que é IA/bot, a menos que o contato pergunte diretamente — aí seja honesto e breve.
"""


def _user_prompt(
    incoming: IncomingMessage,
    *,
    history_text: str,
    forced_tier: str | None,
) -> str:
    meta = [
        f"Chat: {incoming.chat_id}",
        f"Contato: {incoming.contact_label or '(desconhecido)'}",
        f"Grupo: {'sim' if incoming.is_group else 'não'}",
    ]
    if forced_tier:
        meta.append(f"Classificação heurística obrigatória: {forced_tier}")
    block = "\n".join(meta)
    history_block = history_text or "(sem histórico anterior neste chat)"
    return f"""{block}

Histórico recente:
{history_block}

Nova mensagem do contato:
{incoming.text.strip()}
"""


def plan_reply(
    incoming: IncomingMessage,
    thread: ConversationThread,
    *,
    options: ResponderOptions | None = None,
) -> ReplyPlan:
    """Define tier e texto de resposta para uma mensagem recebida."""
    opts = options or ResponderOptions()
    history_text = format_history_for_prompt(thread)
    empty_history = "(sem histórico anterior neste chat)"
    used_history = bool(history_text.strip() and history_text != empty_history)

    heuristic = heuristic_risk_tier(incoming.text)
    if heuristic == "legal_high":
        return ReplyPlan(
            tier="legal_high",
            reply_text=LEGAL_HOLD_TEMPLATE,
            reasons=("heurística jurídica",),
            used_history=used_history,
        )

    forced: str | None = heuristic
    try:
        llm_result: LlmReplyResult = generate_whatsapp_reply(
            system_prompt=_system_prompt(opts),
            user_prompt=_user_prompt(incoming, history_text=history_text, forced_tier=forced),
            gemini_api_key=opts.gemini_api_key,
            openai_api_key=opts.openai_api_key,
            gemini_model=opts.gemini_model,
            openai_model=opts.openai_model,
        )
    except WhatsappLlmError:
        if heuristic == "ambiguous":
            return ReplyPlan(
                tier="ambiguous",
                reply_text=(
                    "Oi! Para eu te responder certinho, pode me dar um pouco mais de contexto "
                    "sobre o que você precisa?"
                ),
                reasons=("fallback sem IA",),
                used_history=used_history,
            )
        return ReplyPlan(
            tier="routine",
            reply_text="Oi! Recebi sua mensagem — já já te respondo com calma por aqui.",
            reasons=("fallback sem IA",),
            used_history=used_history,
        )

    tier = llm_result.tier
    if heuristic == "ambiguous" and tier == "routine":
        tier = "ambiguous"

    reply_text = llm_result.reply_text
    if tier == "legal_high":
        reply_text = LEGAL_HOLD_TEMPLATE

    reasons = llm_result.reasons
    if heuristic:
        reasons = (*reasons, f"heurística:{heuristic}")

    return ReplyPlan(
        tier=tier,
        reply_text=reply_text,
        reasons=reasons,
        used_history=used_history,
    )
