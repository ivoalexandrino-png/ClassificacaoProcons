"""Identificação e extração de e-mails de intimação/push processual.

O parser é o núcleo offline do agente jurídico: recebe o corpo de um e-mail
(intimação, publicação de diário, push de andamento) e extrai os dados
estruturados do processo — número CNJ, tribunal, vara, tipo de movimento,
prazo, data de audiência e link do sistema de andamento.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from typing import Final

from bs4 import BeautifulSoup

# Número único CNJ: NNNNNNN-DD.AAAA.J.TR.OOOO
_CNJ_FORMATTED = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
_CNJ_DIGITS = re.compile(r"\b\d{20}\b")

# Segmentos do número CNJ: J (poder judiciário) e TR (tribunal).
_JUSTICE_BRANCH: Final[dict[str, str]] = {
    "1": "STF",
    "2": "CNJ",
    "3": "STJ",
    "4": "Justiça Federal",
    "5": "Justiça do Trabalho",
    "6": "Justiça Eleitoral",
    "7": "Justiça Militar da União",
    "8": "Justiça Estadual",
    "9": "Justiça Militar Estadual",
}

# Tribunais estaduais mais comuns (segmento 8), por código TR.
_TJ_BY_CODE: Final[dict[str, str]] = {
    "01": "TJAC",
    "02": "TJAL",
    "03": "TJAP",
    "04": "TJAM",
    "05": "TJBA",
    "06": "TJCE",
    "07": "TJDFT",
    "08": "TJES",
    "09": "TJGO",
    "10": "TJMA",
    "11": "TJMT",
    "12": "TJMS",
    "13": "TJMG",
    "14": "TJPA",
    "15": "TJPB",
    "16": "TJPR",
    "17": "TJPE",
    "18": "TJPI",
    "19": "TJRJ",
    "20": "TJRN",
    "21": "TJRS",
    "22": "TJRO",
    "23": "TJRR",
    "24": "TJSC",
    "25": "TJSE",
    "26": "TJSP",
    "27": "TJTO",
}

_TRIBUNAL_KEYWORDS: Final[tuple[str, ...]] = (
    "TJSP",
    "TJRJ",
    "TJMG",
    "TJRS",
    "TJPR",
    "TJSC",
    "TJBA",
    "TJDFT",
    "TRF1",
    "TRF2",
    "TRF3",
    "TRF4",
    "TRF5",
    "TRF6",
    "STJ",
    "STF",
    "TST",
)

_TRT_PATTERN = re.compile(r"\bTRT[\s\-]?(\d{1,2})\b", re.IGNORECASE)

_INTIMACAO_KEYWORDS: Final[tuple[str, ...]] = (
    "intima",
    "intimacao",
    "publicac",
    "andamento",
    "processo n",
    "autos n",
    "movimenta",
    "citac",
    "audiencia",
    "sentenc",
    "despacho",
    "decisao",
    "acordao",
    "diario da justica",
    "diário da justiça",
    "prazo",
)

_MOVEMENT_KEYWORDS: Final[tuple[tuple[str, str], ...]] = (
    ("sentenc", "Sentença"),
    ("acordao", "Acórdão"),
    ("acórdão", "Acórdão"),
    ("embargos de declarac", "Embargos de Declaração"),
    ("agravo", "Agravo"),
    ("apelac", "Apelação"),
    ("recurso", "Recurso"),
    ("citac", "Citação"),
    ("penhora", "Penhora"),
    ("bloqueio", "Bloqueio/Constrição"),
    ("audiencia", "Audiência"),
    ("audiência", "Audiência"),
    ("pericia", "Perícia"),
    ("perícia", "Perícia"),
    ("decisao", "Decisão"),
    ("decisão", "Decisão"),
    ("despacho", "Despacho"),
    ("sanea", "Despacho Saneador"),
    ("contesta", "Contestação"),
    ("manifest", "Manifestação"),
    ("intima", "Intimação"),
)

_PRAZO_PATTERN = re.compile(
    r"prazo\s+(?:comum\s+|sucessivo\s+)?de\s+(?:[a-zç]+\s*)?"
    r"(?:\(?\s*(\d{1,3})\s*\)?)\s*(?:\(?[a-zç]+\)?\s*)?dias?"
    r"(\s+[uú]teis|\s+corridos)?",
    re.IGNORECASE,
)

_PRAZO_WORDS: Final[dict[str, int]] = {
    "cinco": 5,
    "oito": 8,
    "dez": 10,
    "doze": 12,
    "quinze": 15,
    "vinte": 20,
    "trinta": 30,
    "sessenta": 60,
}

_PRAZO_WORD_PATTERN = re.compile(
    r"prazo\s+(?:comum\s+|sucessivo\s+)?de\s+"
    rf"({'|'.join(_PRAZO_WORDS)})\s+dias?"
    r"(\s+[uú]teis|\s+corridos)?",
    re.IGNORECASE,
)

# A data de publicação (art. 224, § 2º) prevalece sobre a de disponibilização.
_PUBLISHED_PATTERN = re.compile(
    r"(?:considera-se\s+public[ao][ao]?|public[ao][ãa]o|publicad[ao])"
    r"[^\d]{0,40}?(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)

_AVAILABLE_PATTERN = re.compile(
    r"(?:disponibilizad[ao]|intimad[ao])[^\d]{0,40}?(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)

_HEARING_PATTERN = re.compile(
    r"audi[êe]ncia[^\d]{0,80}?(\d{2}/\d{2}/\d{4})"
    r"(?:[^\d]{0,15}?(\d{1,2})\s*(?:h|:|horas?)\s*(\d{2})?)?",
    re.IGNORECASE,
)

_VARA_PATTERN = re.compile(
    r"(\d{1,3}[ªaº]?\s*(?:vara|juizado)[^\n,;.]{0,60})",
    re.IGNORECASE,
)

_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedIntimacao:
    """Conteúdo estruturado extraído do corpo de uma intimação."""

    process_number: str | None = None
    tribunal: str | None = None
    vara: str | None = None
    movement_type: str | None = None
    prazo_dias: int | None = None
    prazo_uteis: bool = True
    publication_date: date | None = None
    hearing_at: datetime | None = None
    portal_url: str | None = None
    body_excerpt: str | None = None


class IntimacaoParseError(ValueError):
    """E-mail reconhecido como intimação, mas sem dados extraíveis."""


def normalize_email_address(value: str) -> str:
    """Extrai o endereço de e-mail de um campo From (ex.: 'Nome <email@dominio>')."""
    match = re.search(r"<([^>]+)>", value)
    if match:
        return match.group(1).strip().lower()
    return value.strip().lower()


def _strip_accents_lower(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def looks_like_intimacao(*, subject: str = "", body: str = "") -> bool:
    """Heurística: o e-mail parece uma intimação/publicação/andamento processual?"""
    if _CNJ_FORMATTED.search(body) or _CNJ_FORMATTED.search(subject):
        return True
    haystack = _strip_accents_lower(f"{subject}\n{body}")
    return any(keyword in haystack for keyword in _INTIMACAO_KEYWORDS)


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return unescape(soup.get_text(separator="\n"))


def _extract_process_number(text: str) -> str | None:
    match = _CNJ_FORMATTED.search(text)
    if match:
        return match.group(0)
    digits_match = _CNJ_DIGITS.search(text)
    if digits_match:
        return _format_cnj_digits(digits_match.group(0))
    return None


def _format_cnj_digits(digits: str) -> str:
    return (
        f"{digits[0:7]}-{digits[7:9]}.{digits[9:13]}."
        f"{digits[13:14]}.{digits[14:16]}.{digits[16:20]}"
    )


def derive_tribunal_from_cnj(process_number: str | None) -> str | None:
    """Deriva o tribunal a partir dos segmentos J e TR do número CNJ."""
    if not process_number:
        return None
    match = _CNJ_FORMATTED.search(process_number)
    if not match:
        return None
    parts = match.group(0).split(".")
    branch_code = parts[2]
    tribunal_code = parts[3]
    if branch_code == "8":
        tj = _TJ_BY_CODE.get(tribunal_code)
        if tj:
            return tj
    if branch_code == "4":
        return f"TRF{int(tribunal_code)}" if tribunal_code.isdigit() else "Justiça Federal"
    if branch_code == "5":
        return f"TRT{int(tribunal_code)}" if tribunal_code.isdigit() else "Justiça do Trabalho"
    return _JUSTICE_BRANCH.get(branch_code)


def _extract_tribunal(text: str, process_number: str | None) -> str | None:
    upper = text.upper()
    for keyword in _TRIBUNAL_KEYWORDS:
        if keyword in upper:
            return keyword
    trt_match = _TRT_PATTERN.search(text)
    if trt_match:
        return f"TRT{int(trt_match.group(1))}"
    return derive_tribunal_from_cnj(process_number)


def _extract_vara(text: str) -> str | None:
    match = _VARA_PATTERN.search(text)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip(" .,;")
    return None


def _extract_movement_type(text: str) -> str | None:
    normalized = _strip_accents_lower(text)
    for keyword, label in _MOVEMENT_KEYWORDS:
        if _strip_accents_lower(keyword) in normalized:
            return label
    return None


def _extract_prazo(text: str) -> tuple[int | None, bool]:
    match = _PRAZO_PATTERN.search(text)
    if match:
        dias = int(match.group(1))
        kind = (match.group(2) or "").strip().lower()
        uteis = "corridos" not in kind
        return dias, uteis
    word_match = _PRAZO_WORD_PATTERN.search(text)
    if word_match:
        dias = _PRAZO_WORDS[word_match.group(1).lower()]
        kind = (word_match.group(2) or "").strip().lower()
        uteis = "corridos" not in kind
        return dias, uteis
    return None, True


def _parse_br_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError:
        return None


def _extract_publication_date(text: str) -> date | None:
    match = _PUBLISHED_PATTERN.search(text)
    if match:
        return _parse_br_date(match.group(1))
    fallback = _AVAILABLE_PATTERN.search(text)
    if fallback:
        return _parse_br_date(fallback.group(1))
    return None


def _extract_hearing(text: str) -> datetime | None:
    match = _HEARING_PATTERN.search(text)
    if not match:
        return None
    day = _parse_br_date(match.group(1))
    if day is None:
        return None
    hour = int(match.group(2)) if match.group(2) else 0
    minute = int(match.group(3)) if match.group(3) else 0
    if hour > 23 or minute > 59:
        hour, minute = 0, 0
    return datetime(day.year, day.month, day.day, hour, minute)


def _extract_portal_url(*, html: str | None, text: str) -> str | None:
    if html:
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if href.lower().startswith("http"):
                return href
    match = _URL_PATTERN.search(text)
    if match:
        return match.group(0).rstrip(".,;)")
    return None


def _build_excerpt(text: str, *, limit: int = 500) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed[:limit]


def parse_intimacao_body(
    *,
    html: str | None = None,
    text: str | None = None,
) -> ParsedIntimacao:
    """Extrai os dados estruturados do corpo de um e-mail de intimação.

    Pelo menos um de ``html`` ou ``text`` deve ser informado. Levanta
    :class:`IntimacaoParseError` quando não é possível identificar um número
    de processo — o campo mínimo para o controle no jurídico.
    """
    if not html and not text:
        raise IntimacaoParseError("Corpo do e-mail vazio.")

    normalized_text = text or ""
    if html:
        html_text = _html_to_text(html)
        normalized_text = f"{normalized_text}\n{html_text}".strip()

    process_number = _extract_process_number(normalized_text)
    if not process_number:
        raise IntimacaoParseError("Número do processo (CNJ) não encontrado no corpo do e-mail.")

    prazo_dias, prazo_uteis = _extract_prazo(normalized_text)

    return ParsedIntimacao(
        process_number=process_number,
        tribunal=_extract_tribunal(normalized_text, process_number),
        vara=_extract_vara(normalized_text),
        movement_type=_extract_movement_type(normalized_text),
        prazo_dias=prazo_dias,
        prazo_uteis=prazo_uteis,
        publication_date=_extract_publication_date(normalized_text),
        hearing_at=_extract_hearing(normalized_text),
        portal_url=_extract_portal_url(html=html, text=normalized_text),
        body_excerpt=_build_excerpt(normalized_text),
    )
