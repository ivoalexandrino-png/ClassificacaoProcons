"""Classificação de relevância de mensagens da caixa postal por assunto.

O time quer ignorar o rotineiro (ex.: Escrituração Fiscal Digital do DEC-SP,
recibos de entrega) e ser avisado apenas de assuntos relevantes: fiscalizações,
lançamentos/autos de infração, débitos/atrasos de pagamento, intimações/exigências,
vencimento de certidões e movimentações de processos administrativos.

A regra é allowlist: sem palavra-chave relevante → não classificado (ignorado).
"""

from __future__ import annotations

import os

from classificacao_procons.credentials.mapping import normalize_label
from classificacao_procons.questor.models import IssueSeverity, MensagemCaixaPostal

# Env para acrescentar palavras-chave sem alterar código, conforme surgem assuntos
# novos. Formato: "categoria:palavra" separado por ';' ou ','.
ENV_EXTRA_KEYWORDS = "QUESTOR_RELEVANCIA_EXTRA"

# Rótulo legível e severidade por categoria.
CATEGORY_LABEL: dict[str, str] = {
    "fiscalizacao": "Fiscalização",
    "lancamento": "Lançamento / auto de infração",
    "pagamento": "Débito / atraso de pagamento",
    "intimacao": "Intimação / exigência",
    "autorregularizacao": "Autorregularização",
    "certidao": "Certidão (vencimento)",
    "processo": "Processo administrativo",
}
CATEGORY_SEVERITY: dict[str, IssueSeverity] = {
    "fiscalizacao": "critical",
    "lancamento": "critical",
    "pagamento": "critical",
    "intimacao": "critical",
    "autorregularizacao": "warning",
    "certidao": "warning",
    "processo": "warning",
}

# Ordem importa: categorias críticas antes das de aviso; a primeira que casar vence.
# Palavras já normalizadas (minúsculas, sem acento).
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "fiscalizacao",
        (
            "fiscaliza",
            "malha",
            "omiss",
            "representacao fiscal",
            "termo de exclusao",
            "exclusao do simples",
            "diligencia",
            "nos conformes",
        ),
    ),
    (
        "lancamento",
        (
            "auto de infrac",
            "lancamento",
            "notificacao de lancamento",
            "lancado de oficio",
            "multa",
        ),
    ),
    (
        "intimacao",
        ("intima", "exigenc", "notificacao fiscal", "termo de inicio", "notificacao para"),
    ),
    (
        "pagamento",
        (
            "debito",
            "divida ativa",
            "cobranc",
            "atraso",
            "inadimpl",
            "em aberto",
            "nao pago",
            "parcelament",
            "pendencia de pagamento",
            "guia nao paga",
            "cadin",
            "compensacao de oficio",
            "programa especial de parcelamento",
            "pep -",
        ),
    ),
    (
        "autorregularizacao",
        ("autorregulariza", "auto regulariza", "regularizacao"),
    ),
    (
        "certidao",
        ("vencimento de certid", "certidao vencida", "vencimento certid", "certid"),
    ),
    (
        "processo",
        (
            "e-processo",
            "juntada",
            "processo administrativo",
            "andamento processual",
            "ciencia do processo",
            "per/dcomp",
            "despacho decis",
        ),
    ),
)


def _extra_rules() -> list[tuple[str, str]]:
    """Palavras-chave extras vindas da env (categoria:palavra)."""
    raw = os.environ.get(ENV_EXTRA_KEYWORDS, "").strip()
    if not raw:
        return []
    pairs: list[tuple[str, str]] = []
    for token in raw.replace(";", ",").split(","):
        token = token.strip()
        if ":" not in token:
            continue
        category, keyword = token.split(":", 1)
        category = category.strip().lower()
        keyword = normalize_label(keyword)
        if category in CATEGORY_LABEL and keyword:
            pairs.append((category, keyword))
    return pairs


def classify_caixa_message(
    mensagem: MensagemCaixaPostal,
) -> tuple[str, str, IssueSeverity] | None:
    """Classifica a mensagem por assunto/remetente.

    Retorna ``(categoria, rótulo, severidade)`` quando relevante, ou ``None``
    quando rotineira/irrelevante (deve ser ignorada por padrão).
    """
    haystack = normalize_label(
        " ".join(
            part
            for part in (mensagem.assunto, mensagem.remetente, mensagem.categoria)
            if part
        ),
    )
    if not haystack:
        return None
    # Extras da env têm prioridade (permitem corrigir rapidamente classificações).
    for category, keyword in _extra_rules():
        if keyword in haystack:
            return category, CATEGORY_LABEL[category], CATEGORY_SEVERITY[category]
    for category, keywords in _RULES:
        if any(keyword in haystack for keyword in keywords):
            return category, CATEGORY_LABEL[category], CATEGORY_SEVERITY[category]
    return None
