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
)

_CUSTAS_PATH_KEYWORDS: tuple[str, ...] = (
    "custas",
    "taxa judiciaria",
    "guia de recolhimento",
    "preparo",
)

_PRIORITY_PATH_KEYWORDS: tuple[str, ...] = (
    "deposito",
    "dep jud",
    "dep. jud",
    "condenacao",
    "condenação",
    "pagamento cond",
    "debito judicial",
    "comprov pagamento",
    "comprovante de pagamento",
    "guia",
    "planilha debito",
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
    return any(keyword in normalized for keyword in _PRIORITY_PATH_KEYWORDS)


def should_analyze_pdf(*, drive_path: str, file_name: str) -> bool:
    if should_skip_pdf_by_path(drive_path):
        return False
    if not file_name.casefold().endswith(".pdf"):
        # Guias às vezes vêm sem extensão; analisar se o caminho indicar depósito.
        return path_suggests_deposit_workflow(drive_path)
    return True
