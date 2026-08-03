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
    "aprovar",
    "mp",
    "abdofast",
    "glam",
    "nutri",
    "wiki",
    "intense",
    "deo",
    "colonias",
    "colônias",
    "scrub",
    "copy",
    },
)

_DATE_DMY = re.compile(r"^\d{1,2}[./]\d{1,2}[./]\d{2,4}$")
_PERIOD_YYYYMM = re.compile(r"^20\d{4}$")
_PERIOD_YYMMDD = re.compile(r"^\d{6}$")
_SUFFIX_COPY = re.compile(r"\(\s*copy\s*\)$", re.IGNORECASE)
_SUFFIX_NUMERIC_COPY = re.compile(r"\(\d+\)$")
_MIN_SUBSTRING_LEN = 18
_MONTH_TOKEN = re.compile(
    r"^(jan|janeiro|fev|fevereiro|mar|marco|março|abr|abril|mai|maio|jun|junho|jul|julho|"
    r"ago|agosto|set|setembro|out|outubro|nov|novembro|dez|dezembro)$",
    re.IGNORECASE,
)


def normalize_controle_title(value: str) -> str:
    """Normaliza título para comparação (público)."""
    return _normalize_controle_name(value)


def _normalize_controle_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    cleaned = _SUFFIX_COPY.sub("", without_marks)
    cleaned = _SUFFIX_NUMERIC_COPY.sub("", cleaned)
    if cleaned.endswith(".docx"):
        cleaned = cleaned[: -len(".docx")]
    cleaned = re.sub(r"_+", " ", cleaned)
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


def _month_year_slug(document_name: str) -> str | None:
    """Ex.: ``jun_2026``, ``Junho_2026``, ``fev/25`` → ``2026-06`` / ``2025-02``."""
    normalized = _normalize_controle_name(document_name)
    match = re.search(r"(20\d{2})", normalized)
    year_from_token = match.group(1) if match else None
    month_num: int | None = None
    for part in re.split(r"[\s\-–—/,_]+", normalized):
        token = part.strip()
        if not token:
            continue
        month_match = _MONTH_TOKEN.match(token)
        if month_match:
            month_num = _month_name_to_number(month_match.group(1))
            continue
        combo = re.match(r"^(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)(\d{2})$", token)
        if combo:
            month_num = _month_name_to_number(combo.group(1))
            if not year_from_token:
                year_from_token = f"20{combo.group(2)}"
    if month_num is None:
        slash = re.search(r"(\d{1,2})\s*/\s*(\d{2,4})", normalized)
        if slash:
            month_num = int(slash.group(1))
            yy = slash.group(2)
            year_from_token = yy if len(yy) == 4 else f"20{yy}"
    if month_num is None or not year_from_token:
        return None
    return f"{year_from_token}-{month_num:02d}"


def _month_name_to_number(name: str) -> int:
    key = name.casefold().replace("ç", "c")
    mapping = {
        "jan": 1,
        "janeiro": 1,
        "fev": 2,
        "fevereiro": 2,
        "mar": 3,
        "marco": 3,
        "abr": 4,
        "abril": 4,
        "mai": 5,
        "maio": 5,
        "jun": 6,
        "junho": 6,
        "jul": 7,
        "julho": 7,
        "ago": 8,
        "agosto": 8,
        "set": 9,
        "setembro": 9,
        "out": 10,
        "outubro": 10,
        "nov": 11,
        "novembro": 11,
        "dez": 12,
        "dezembro": 12,
    }
    return mapping[key]


def extract_pedido_supplier_slug(document_name: str) -> str | None:
    """Fornecedor em títulos de pedido MP (ex.: ``brass hill``)."""
    normalized = _normalize_controle_name(document_name)
    if "pedido" not in normalized and "aprovar" not in normalized:
        return None
    if "brass hill" in normalized or "brasshill" in normalized.replace(" ", ""):
        return "brass_hill"
    if "henlau" in normalized:
        return "henlau"
    if "nobilis" in normalized:
        return "nobilis"
    return None


def extract_pedido_lot_key(document_name: str) -> tuple[str, str] | None:
    """Chave (fornecedor, lote mês/ano) para não duplicar o mesmo pedido no Monday."""
    supplier = extract_pedido_supplier_slug(document_name)
    period = _month_year_slug(document_name)
    if supplier and period:
        return supplier, period
    return None


def controle_names_likely_same_contract(
    autentique_name: str,
    monday_item_name: str,
) -> bool:
    """Indica se títulos diferentes são o mesmo contrato (não só o mesmo fornecedor)."""
    if normalized_controle_titles_equal(autentique_name, monday_item_name):
        return True

    left_lot = extract_pedido_lot_key(autentique_name)
    right_lot = extract_pedido_lot_key(monday_item_name)
    if left_lot and right_lot and left_lot == right_lot:
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
