"""Deduplicação de itens do Controle Assinaturas (nome vs Autentique).

Regra de negócio (conservadora):

1. **Autentique ID** na coluna de link → mesma chave (tratado fora deste módulo).
2. **Título idêntico** após normalização → mesmo contrato.
3. **Título parecido** só quando há evidência forte de ser o *mesmo* documento,
   não vários contratos do mesmo fornecedor (ex.: série ``202505_BrassHill`` vs
   ``202503_BrassHill`` são **diferentes** — só ``BrassHill`` em comum não basta).

Critérios de título parecido (qualquer um):

- um título normalizado contém o outro e o menor tem ≥ 18 caracteres;
- ≥ 3 tokens distintivos em comum (fora stopwords);
- ≥ 2 tokens em comum **e** o mesmo marcador de período (``202505``, ``23.07.2026``, etc.).
"""

from __future__ import annotations

import re
import unicodedata

from classificacao_procons.contratos.models import ControleAssinaturasItem

_NAME_STOPWORDS: frozenset[str] = frozenset(
    {
        "contrato",
        "contratos",
        "minuta",
        "minutas",
        "padrao",
        "padrão",
        "modelo",
        "b2b",
        "b4a",
        "aditivo",
        "distrato",
        "parceria",
        "comercial",
        "fornecimento",
        "prestacao",
        "prestação",
        "servicos",
        "serviços",
        "empresa",
        "termo",
        "acordo",
        "nda",
        "anexo",
        "lab",
        "residual",
        "pedido",
        "reposicao",
        "reposição",
        "mlm",
    },
)

_DATE_DMY = re.compile(r"^\d{1,2}[./]\d{1,2}[./]\d{2,4}$")
_PERIOD_YYYYMM = re.compile(r"^20\d{4}$")
_PERIOD_YYMMDD = re.compile(r"^\d{6}$")
_SUFFIX_COPY = re.compile(r"\(\d+\)$")
_MIN_SUBSTRING_LEN = 18


def normalize_controle_title(value: str) -> str:
    """Normaliza título para comparação (público)."""
    return _normalize_controle_name(value)


def _normalize_controle_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    cleaned = _SUFFIX_COPY.sub("", without_marks)
    return re.sub(r"\s+", " ", cleaned).strip()


def normalized_controle_titles_equal(left: str, right: str) -> bool:
    """Títulos iguais após normalização (acentos, espaços, sufixo ``(1)``)."""
    a = _normalize_controle_name(left)
    b = _normalize_controle_name(right)
    return bool(a) and a == b


def extract_controle_name_tokens(document_name: str) -> set[str]:
    """Tokens distintivos do título (fora stopwords e períodos isolados)."""
    normalized = _normalize_controle_name(document_name)
    raw_parts = re.split(r"[\s\-–—/,_]+", normalized)
    tokens: set[str] = set()
    for part in raw_parts:
        token = part.strip()
        if len(token) < 3:
            continue
        if _DATE_DMY.match(token) or _PERIOD_YYYYMM.match(token) or _PERIOD_YYMMDD.match(token):
            continue
        if token in _NAME_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def extract_controle_period_tokens(document_name: str) -> set[str]:
    """Marcadores de vigência/lote no título (datas e ``YYYYMM``)."""
    normalized = _normalize_controle_name(document_name)
    periods: set[str] = set()
    for part in re.split(r"[\s\-–—/,_]+", normalized):
        token = part.strip()
        if _DATE_DMY.match(token) or _PERIOD_YYYYMM.match(token) or _PERIOD_YYMMDD.match(token):
            periods.add(token)
    return periods


def controle_names_likely_same_contract(
    autentique_name: str,
    monday_item_name: str,
) -> bool:
    """Indica se títulos diferentes são o mesmo contrato (não só o mesmo fornecedor)."""
    if normalized_controle_titles_equal(autentique_name, monday_item_name):
        return True

    left = _normalize_controle_name(autentique_name)
    right = _normalize_controle_name(monday_item_name)
    if not left or not right:
        return False

    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if len(shorter) >= _MIN_SUBSTRING_LEN and shorter in longer:
        return True

    left_tokens = extract_controle_name_tokens(autentique_name)
    right_tokens = extract_controle_name_tokens(monday_item_name)
    overlap = left_tokens & right_tokens
    if len(overlap) >= 3:
        return True

    if len(overlap) >= 2:
        left_periods = extract_controle_period_tokens(autentique_name)
        right_periods = extract_controle_period_tokens(monday_item_name)
        if left_periods and right_periods and left_periods & right_periods:
            return True

    return False


def find_likely_name_matches(
    *,
    document_name: str,
    items: tuple[ControleAssinaturasItem, ...] | list[ControleAssinaturasItem],
) -> tuple[ControleAssinaturasItem, ...]:
    return tuple(
        item
        for item in items
        if controle_names_likely_same_contract(document_name, item.name)
    )
