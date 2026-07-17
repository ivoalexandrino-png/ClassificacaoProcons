"""Classificação da providência necessária a partir de uma intimação."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from classificacao_procons.juridico.deadlines import calculate_prazo_final
from classificacao_procons.juridico.models import IntimacaoEmail, Providencia

# Palavras-chave do movimento → (tipo de providência, exige ação, prazo padrão).
# ``prazo_padrao`` (em dias úteis) é usado apenas quando a intimação não traz
# um prazo explícito; ``None`` mantém o prazo em aberto.
_PROVIDENCIA_RULES: tuple[tuple[str, str, bool, int | None], ...] = (
    ("audiência", "Audiência", True, None),
    ("audiencia", "Audiência", True, None),
    ("citação", "Contestar", True, 15),
    ("citacao", "Contestar", True, 15),
    ("contesta", "Contestar", True, 15),
    ("sentença", "Analisar recurso", True, 15),
    ("sentenca", "Analisar recurso", True, 15),
    ("acórdão", "Analisar recurso", True, 15),
    ("acordao", "Analisar recurso", True, 15),
    ("embargos", "Manifestar", True, 5),
    ("agravo", "Contrarrazões", True, 15),
    ("apelação", "Contrarrazões", True, 15),
    ("apelacao", "Contrarrazões", True, 15),
    ("recurso", "Contrarrazões", True, 15),
    ("penhora", "Manifestar sobre constrição", True, 5),
    ("bloqueio", "Manifestar sobre constrição", True, 5),
    ("perícia", "Manifestar", True, 15),
    ("pericia", "Manifestar", True, 15),
    ("decisão", "Cumprir/Manifestar", True, None),
    ("decisao", "Cumprir/Manifestar", True, None),
    ("despacho", "Cumprir/Manifestar", True, None),
    ("manifest", "Manifestar", True, None),
    ("intimação", "Manifestar", True, None),
    ("intimacao", "Manifestar", True, None),
)

# Movimentos meramente informativos: não exigem ação, apenas acompanhamento.
_INFORMATIVE_KEYWORDS: tuple[str, ...] = (
    "juntada",
    "certidão",
    "certidao",
    "conclusos",
    "distribuíd",
    "distribuid",
    "mero expediente",
    "publicado",
    "arquivamento",
    "baixa definitiva",
    "trânsito em julgado",
    "transito em julgado",
)

STATUS_A_PROVIDENCIAR = "A providenciar"
STATUS_ACOMPANHAR = "Acompanhar"


def _strip_accents_lower(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _match_rule(movement_type: str | None, body: str) -> tuple[str, bool, int | None] | None:
    haystack = _strip_accents_lower(f"{movement_type or ''}\n{body}")
    for keyword, tipo, requires_action, prazo_padrao in _PROVIDENCIA_RULES:
        if _strip_accents_lower(keyword) in haystack:
            return tipo, requires_action, prazo_padrao
    return None


def _is_informative(body: str) -> bool:
    haystack = _strip_accents_lower(body)
    return any(_strip_accents_lower(keyword) in haystack for keyword in _INFORMATIVE_KEYWORDS)


def classify_providencia(
    intimacao: IntimacaoEmail,
    *,
    holidays: Iterable[date] | None = None,
    today: date | None = None,
) -> Providencia:
    """Determina a providência (tipo, prazo final e/ou audiência) de uma intimação.

    O prazo final é calculado com :func:`calculate_prazo_final` a partir da data
    de publicação (ou de hoje, como fallback) e do prazo em dias — explícito na
    intimação ou o padrão do tipo de movimento.
    """
    body = intimacao.body_excerpt or ""

    if intimacao.hearing_at is not None:
        return Providencia(
            process_number=intimacao.process_number or "",
            tipo="Audiência",
            descricao=_describe(intimacao, "Audiência designada"),
            hearing_at=intimacao.hearing_at,
            requires_action=True,
            status=STATUS_A_PROVIDENCIAR,
        )

    rule = _match_rule(intimacao.movement_type, body)
    base_date = intimacao.publication_date or today or date.today()

    prazo_dias = intimacao.prazo_dias
    tipo = intimacao.movement_type or "Intimação"
    requires_action = True
    if rule is not None:
        tipo, requires_action, prazo_padrao = rule
        if prazo_dias is None:
            prazo_dias = prazo_padrao

    if rule is None and prazo_dias is None and _is_informative(body):
        return Providencia(
            process_number=intimacao.process_number or "",
            tipo=intimacao.movement_type or "Andamento",
            descricao=_describe(intimacao, "Andamento informativo"),
            requires_action=False,
            status=STATUS_ACOMPANHAR,
        )

    prazo_final: date | None = None
    if prazo_dias is not None:
        prazo_final = calculate_prazo_final(
            publication_date=base_date,
            dias=prazo_dias,
            business_days=intimacao.prazo_uteis,
            holidays=holidays,
        )

    return Providencia(
        process_number=intimacao.process_number or "",
        tipo=tipo,
        descricao=_describe(intimacao, tipo),
        prazo_final=prazo_final,
        requires_action=requires_action,
        status=STATUS_A_PROVIDENCIAR,
    )


def _describe(intimacao: IntimacaoEmail, tipo: str) -> str:
    parts = [tipo]
    if intimacao.movement_type and intimacao.movement_type != tipo:
        parts.append(intimacao.movement_type)
    if intimacao.tribunal:
        parts.append(intimacao.tribunal)
    if intimacao.vara:
        parts.append(intimacao.vara)
    return " — ".join(parts)
