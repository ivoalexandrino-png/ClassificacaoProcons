"""Classificação de relevância de mensagens da caixa postal por assunto.

O time quer ignorar o rotineiro (ex.: Escrituração Fiscal Digital do DEC-SP,
recibos de entrega) e ser avisado apenas de assuntos relevantes: fiscalizações,
lançamentos/autos de infração, débitos/atrasos de pagamento, intimações/exigências,
vencimento de certidões e movimentações de processos administrativos.

A regra é allowlist: sem palavra-chave relevante → não classificado (ignorado).
"""

from __future__ import annotations

from classificacao_procons.credentials.mapping import normalize_label
from classificacao_procons.questor.models import IssueSeverity, MensagemCaixaPostal

# Rótulo legível e severidade por categoria.
CATEGORY_LABEL: dict[str, str] = {
    "fiscalizacao": "Fiscalização",
    "lancamento": "Lançamento / auto de infração",
    "pagamento": "Débito / atraso de pagamento",
    "intimacao": "Intimação / exigência",
    "certidao": "Certidão (vencimento)",
    "processo": "Processo administrativo",
}
CATEGORY_SEVERITY: dict[str, IssueSeverity] = {
    "fiscalizacao": "critical",
    "lancamento": "critical",
    "pagamento": "critical",
    "intimacao": "critical",
    "certidao": "warning",
    "processo": "warning",
}

# Ordem importa: categorias críticas antes das de aviso; a primeira que casar vence.
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
        ),
    ),
    (
        "lancamento",
        ("auto de infrac", "lancamento", "notificacao de lancamento", "lancado de oficio"),
    ),
    (
        "intimacao",
        ("intima", "exigenc", "notificacao fiscal", "termo de inicio"),
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
        ),
    ),
    (
        "certidao",
        ("vencimento de certid", "certidao vencida", "vencimento certid", "certid"),
    ),
    (
        "processo",
        ("e-processo", "juntada", "processo administrativo", "andamento processual"),
    ),
)


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
    for category, keywords in _RULES:
        if any(keyword in haystack for keyword in keywords):
            return category, CATEGORY_LABEL[category], CATEGORY_SEVERITY[category]
    return None
