"""Política de seleção de mensagens da caixa postal para alerta.

A caixa postal costuma ter um backlog grande de mensagens não lidas rotineiras
(ex.: Escrituração Fiscal Digital do DEC-SP), enquanto o flag "Relevante" do
Questor é pouco usado. Alertar sobre *todas* as não lidas gera ruído; alertar só
sobre "relevantes" pode não pegar nada. Por isso a seleção é configurável, com um
default que prioriza mensagens relevantes ou com prazo de ciência.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from classificacao_procons.questor.models import MensagemCaixaPostal
from classificacao_procons.questor.relevancia import classify_caixa_message

CAIXA_MODES = (
    "todas",
    "relevantes",
    "relevante_ou_prazo",
    "relevantes_por_assunto",
    "recentes",
)
DEFAULT_CAIXA_MODE = "relevantes_por_assunto"
DEFAULT_UNREAD_WINDOW_DAYS = 15


def select_actionable_messages(
    mensagens: tuple[MensagemCaixaPostal, ...] | list[MensagemCaixaPostal],
    *,
    mode: str = DEFAULT_CAIXA_MODE,
    window_days: int = DEFAULT_UNREAD_WINDOW_DAYS,
    today: date | None = None,
) -> list[MensagemCaixaPostal]:
    """Seleciona as mensagens não lidas que merecem alerta, conforme ``mode``.

    - ``todas``: toda mensagem não lida.
    - ``relevantes``: apenas não lidas marcadas como relevantes (flag do Questor).
    - ``relevantes_por_assunto`` (default): não lidas classificadas como relevantes
      pelo assunto (fiscalização, lançamento, atraso de pagamento, intimação,
      vencimento de certidão, processo) — ou com flag relevante, ou com prazo.
    - ``relevante_ou_prazo``: não lidas relevantes (flag) ou com prazo de ciência.
    - ``recentes``: as de ``relevante_ou_prazo`` mais as recebidas na janela recente.
    """
    if mode not in CAIXA_MODES:
        raise ValueError(f"Modo de caixa postal inválido: {mode!r}. Use um de {CAIXA_MODES}.")

    unread = [m for m in mensagens if not m.lida]
    if mode == "todas":
        return unread
    if mode == "relevantes":
        return [m for m in unread if m.relevante]
    if mode == "relevantes_por_assunto":
        return [
            m
            for m in unread
            if classify_caixa_message(m) is not None
            or m.relevante
            or m.prazo_ciencia is not None
        ]
    if mode == "recentes":
        reference = today or date.today()
        cutoff = reference - timedelta(days=window_days)
        return [
            m
            for m in unread
            if m.relevante
            or m.prazo_ciencia is not None
            or (m.data_postagem is not None and m.data_postagem >= cutoff)
        ]
    return [m for m in unread if m.relevante or m.prazo_ciencia is not None]


def unread_summary(
    mensagens: tuple[MensagemCaixaPostal, ...] | list[MensagemCaixaPostal],
) -> str | None:
    """Resumo textual do backlog não lido por domicílio (para contexto no e-mail)."""
    unread = [m for m in mensagens if not m.lida]
    if not unread:
        return None
    by_domicilio = Counter(m.orgao for m in unread)
    partes = ", ".join(f"{orgao}: {qtd}" for orgao, qtd in sorted(by_domicilio.items()))
    return f"Backlog de {len(unread)} mensagem(ns) não lida(s) na caixa postal ({partes})."
