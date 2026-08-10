"""Classificação de guias/comprovantes de custas pelo texto."""

from __future__ import annotations

import re
import unicodedata

from classificacao_procons.juridico.custas.models import CourtFeeType

_CUSTAS_TEXT_KEYWORDS: tuple[str, ...] = (
    "custas processuais",
    "taxa judiciaria",
    "taxa judiciária",
    "guia de recolhimento",
    "custas iniciais",
    "custas finais",
    "custas do recurso",
    "custas de recurso",
    "preparo",
    "fundesp",
    "dare-sp",
    "dare sp",
)

_DEPOSIT_TEXT_KEYWORDS: tuple[str, ...] = (
    "deposito judicial",
    "depósito judicial",
    "conta judicial",
    "sistema djo",
    "guia de deposito",
    "guia de depósito",
    "dep. jud",
)

_NOISE_KEYWORDS: tuple[str, ...] = (
    "comprovante de entrega",
    "jadlog",
    "cancelamento da assinatura",
)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


def is_court_fees_document(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    if any(keyword in normalized for keyword in _NOISE_KEYWORDS):
        return False
    if any(keyword in normalized for keyword in _DEPOSIT_TEXT_KEYWORDS):
        return False
    return any(keyword in normalized for keyword in _CUSTAS_TEXT_KEYWORDS)


def has_strong_custas_signal(text: str) -> bool:
    normalized = _normalize(text)
    return any(keyword in normalized for keyword in _CUSTAS_TEXT_KEYWORDS)


def infer_fee_type(*, text: str, drive_path: str) -> CourtFeeType:
    combined = _normalize(f"{drive_path}\n{text}")
    if any(k in combined for k in ("recurso", "apelacao", "apelação", "inominado")):
        return CourtFeeType.APPEAL
    if any(k in combined for k in ("custas finais", "custas final")):
        return CourtFeeType.FINAL
    if any(k in combined for k in ("custas iniciais", "custas inicial", "distribuicao")):
        return CourtFeeType.INITIAL
    if "preparo" in combined:
        return CourtFeeType.PREPARO
    if any(k in combined for k in ("intimacao", "intimação", "despesas de intimacao")):
        return CourtFeeType.INTIMATION
    return CourtFeeType.OTHER
