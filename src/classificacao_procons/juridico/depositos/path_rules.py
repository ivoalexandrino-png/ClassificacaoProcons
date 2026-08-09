"""Heurísticas de caminho para pular PDFs claramente irrelevantes."""

from __future__ import annotations

import re
import unicodedata


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


_SKIP_PATH_KEYWORDS: tuple[str, ...] = (
    "comprovante de entrega",
    "comprovante de cancelamento",
    "comprovante de estorno",
    "historico pagamento",
    "area da assinante",
    "jadlog",
    "correios",
    "rastreio",
    "procuracao",
    "substabelecimento",
    "preposicao",
    "carta de preposicao",
    "contestacao",
    "contestação",
    "recurso inominado",
    "recurso de apelacao",
    "recurso de apelação",
    "audiencia",
    "audiência",
    "atendimento procon",
    "pet. 001",
    "peticao inicial",
)

_CUSTAS_PATH_KEYWORDS: tuple[str, ...] = (
    "custas",
    "taxa judiciaria",
    "guia de recolhimento",
    "preparo",
)

_DEPOSIT_PATH_KEYWORDS: tuple[str, ...] = (
    "deposito",
    "dep jud",
    "dep. jud",
    "condenacao",
    "condenação",
    "pagamento cond",
    "debito judicial",
    "comprov pagamento",
    "comprov. pagamento",
    "comprovante de pagamento",
    "junt comprov",
    "junt. comprov",
    "juntada comprovante",
    "planilha debito",
    "guia dep",
    "guia de dep",
    "pag. int",
    "pagamento int",
    "parcelamento",
    "guia parcelamento",
)

_DEPOSIT_FILENAME_KEYWORDS: tuple[str, ...] = (
    "guia dep",
    "guia de dep",
    "deposito",
    "dep jud",
    "debito judicial",
    "planilha debito",
    "comprov",
)


def should_skip_pdf_by_path(drive_path: str) -> bool:
    normalized = _normalize(drive_path)
    if any(keyword in normalized for keyword in _SKIP_PATH_KEYWORDS):
        return True
    if normalized.endswith("/informacoes") or "/informacoes/" in normalized:
        return True
    return False


def path_suggests_court_fees(drive_path: str) -> bool:
    normalized = _normalize(drive_path)
    return any(keyword in normalized for keyword in _CUSTAS_PATH_KEYWORDS)


def path_suggests_deposit_workflow(drive_path: str) -> bool:
    normalized = _normalize(drive_path)
    if path_suggests_court_fees(normalized):
        return False
    return any(keyword in normalized for keyword in _DEPOSIT_PATH_KEYWORDS)


def _filename_suggests_deposit(file_name: str) -> bool:
    normalized = _normalize(file_name)
    if any(keyword in normalized for keyword in ("entrega", "estorno", "cancelamento")):
        return False
    return any(keyword in normalized for keyword in _DEPOSIT_FILENAME_KEYWORDS)


def should_analyze_pdf(*, drive_path: str, file_name: str) -> bool:
    if should_skip_pdf_by_path(drive_path):
        return False
    if path_suggests_deposit_workflow(drive_path):
        return True
    if not file_name.casefold().endswith(".pdf"):
        return False
    return _filename_suggests_deposit(file_name)


def deposit_document_priority(*, drive_path: str, file_name: str) -> int:
    """Maior = preferir na deduplicação (comprovante > guia)."""
    combined = _normalize(f"{drive_path}/{file_name}")
    if "comprov" in combined:
        return 3
    if "guia" in combined:
        return 2
    if "planilha" in combined:
        return 1
    return 0
