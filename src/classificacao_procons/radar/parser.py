"""Normalização de texto de editais para os modelos do radar.

Os títulos/resumos das fontes de fomento variam muito (idioma, jargão de cada
agência). Estas funções são tolerantes (comparação sem acento/caixa) para
classificar a área temática, a abrangência e a situação a partir de texto livre.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

from classificacao_procons.radar.models import Area, EditalStatus, Scope

# Palavras-chave por área (folded: minúsculas, sem acento). Cobrem português e
# inglês, já que o radar mistura fontes nacionais e internacionais.
_AREA_KEYWORDS: dict[Area, tuple[str, ...]] = {
    "direito": (
        "direito",
        "juridic",  # juridico/jurídica/juridical
        "juridico",
        "legal",
        "law",
        "justica",
        "justice",
        "direitos humanos",
        "human rights",
        "criminolog",
        "constituc",
        "processual",
        "advocac",
        "rule of law",
    ),
    "saude": (
        "saude",
        "health",
        "medic",  # medicina/médico/medical/medicine
        "enfermag",
        "nursing",
        "clinic",
        "epidemiolog",
        "farmac",  # farmacia/farmacologia/pharma
        "pharma",
        "biomedic",
        "hospital",
        "doenca",
        "disease",
        "cancer",
        "oncolog",
        "public health",
        "saude publica",
        "vacina",
        "vaccine",
        "mental health",
        "saude mental",
    ),
    "administracao": (
        "administracao",
        "administration",
        "gestao",
        "management",
        "negocios",
        "business",
        "empreendedor",
        "entrepreneur",
        "governanca",
        "governance",
        "politicas publicas",
        "public policy",
        "public administration",
        "financas",
        "finance",
        "economia",
        "economics",
        "marketing",
        "recursos humanos",
    ),
    "educacao": (
        "educacao",
        "education",
        "ensino",
        "teaching",
        "pedagog",
        "escolar",
        "school",
        "docente",
        "aprendizag",
        "learning",
        "alfabetiz",
        "literacy",
        "curricul",
        "formacao de professores",
        "teacher training",
        "educacao superior",
        "higher education",
    ),
}

# Marcadores que indicam que o texto é, de fato, um edital/chamada/oportunidade.
_EDITAL_MARKERS: tuple[str, ...] = (
    "edital",
    "chamada",
    "chamamento",
    "selecao",
    "bolsa",
    "fomento",
    "financiamento",
    "call for proposals",
    "call for applications",
    "funding",
    "grant",
    "fellowship",
    "scholarship",
    "award",
    "request for proposals",
    "convocatoria",
    "oportunidade",
)

_INTERNATIONAL_MARKERS: tuple[str, ...] = (
    "internacional",
    "international",
    "global",
    "horizon",
    "erc",
    "european",
    "worldwide",
    "cooperacao internacional",
)

_OPEN_MARKERS: tuple[str, ...] = (
    "aberto",
    "abertas",
    "inscricoes abertas",
    "submissoes abertas",
    "now open",
    "open call",
    "currently open",
    "receiving applications",
    "prazo ate",
)

_UPCOMING_MARKERS: tuple[str, ...] = (
    "previst",  # previsto/prevista
    "em breve",
    "proximamente",
    "upcoming",
    "coming soon",
    "forthcoming",
    "a ser lancad",
)

_CLOSED_MARKERS: tuple[str, ...] = (
    "encerrad",  # encerrado/encerrada
    "finalizad",
    "resultado",
    "closed",
    "expired",
    "deadline passed",
    "inscricoes encerradas",
)


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def fold(value: str | None) -> str:
    """Minúsculas, sem acento e com espaços colapsados (bom para comparar)."""
    if not value:
        return ""
    return " ".join(_strip_accents(value).casefold().split())


def looks_like_edital(text: str | None) -> bool:
    """Heurística: o texto parece anunciar um edital/chamada/oportunidade?"""
    folded = fold(text)
    if not folded:
        return False
    return any(marker in folded for marker in _EDITAL_MARKERS)


def classify_areas(*texts: str | None) -> tuple[Area, ...]:
    """Detecta as áreas temáticas presentes no texto (0, 1 ou mais).

    Junta todos os textos fornecidos (título, resumo, categoria...) e devolve as
    áreas do núcleo (direito/saúde/administração/educação) cujas palavras-chave
    aparecem. A ordem segue ``_AREA_KEYWORDS`` para ser determinística.
    """
    folded = " ".join(fold(text) for text in texts if text)
    if not folded:
        return ()
    matched: list[Area] = []
    for area, keywords in _AREA_KEYWORDS.items():
        if any(keyword in folded for keyword in keywords):
            matched.append(area)
    return tuple(matched)


def detect_scope(*texts: str | None, default: Scope = "nacional") -> Scope:
    """Classifica a abrangência como nacional/internacional a partir do texto."""
    folded = " ".join(fold(text) for text in texts if text)
    if folded and any(marker in folded for marker in _INTERNATIONAL_MARKERS):
        return "internacional"
    return default


def detect_status(*texts: str | None) -> EditalStatus:
    """Classifica a situação do edital a partir do texto (aberto/previsto/...)."""
    folded = " ".join(fold(text) for text in texts if text)
    if not folded:
        return "desconhecido"
    if any(marker in folded for marker in _CLOSED_MARKERS):
        return "encerrado"
    if any(marker in folded for marker in _OPEN_MARKERS):
        return "aberto"
    if any(marker in folded for marker in _UPCOMING_MARKERS):
        return "previsto"
    return "desconhecido"


_MONTHS_PT = {
    "jan": 1,
    "fev": 2,
    "mar": 3,
    "abr": 4,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "set": 9,
    "out": 10,
    "nov": 11,
    "dez": 12,
}

_EXTENDED_DATE_RE = re.compile(
    r"(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})",
    re.IGNORECASE,
)


def parse_date(value: str | None) -> date | None:
    """Interpreta datas em vários formatos (BR, ISO, RFC 822 e por extenso)."""
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    # ISO 8601 com hora/tz (ex.: feeds Atom: 2026-08-09T10:00:00Z).
    iso_candidate = cleaned.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_candidate).date()
    except ValueError:
        pass

    # RFC 822 (RSS pubDate, ex.: "Sat, 09 Aug 2026 10:00:00 +0000").
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    # Data por extenso em português (ex.: "9 de agosto de 2026").
    match = _EXTENDED_DATE_RE.search(cleaned)
    if match:
        day = int(match.group(1))
        month = _MONTHS_PT.get(_strip_accents(match.group(2)).casefold()[:3])
        year = int(match.group(3))
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                return None
    return None
