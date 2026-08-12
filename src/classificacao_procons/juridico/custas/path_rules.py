"""Heurísticas de caminho para custas (exclui depósitos judiciais)."""

from __future__ import annotations

import re
import unicodedata

from classificacao_procons.juridico.depositos.path_rules import (
    path_suggests_court_fees,
    path_suggests_deposit_workflow,
)

# Mesmas pastas operacionais irrelevantes que depósitos, exceto recurso/apelação
# (guias de custas/preparo costumam ficar nessas pastas).
_CUSTAS_SKIP_PATH_KEYWORDS: tuple[str, ...] = (
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
    "audiencia",
    "audiência",
    "atendimento procon",
    "pet. 001",
    "peticao inicial",
)


def should_skip_pdf_by_path_for_custas(drive_path: str) -> bool:
    normalized = _normalize(drive_path)
    if any(keyword in normalized for keyword in _CUSTAS_SKIP_PATH_KEYWORDS):
        return True
    if normalized.endswith("/informacoes") or "/informacoes/" in normalized:
        return True
    return False

_CUSTAS_FILENAME_KEYWORDS: tuple[str, ...] = (
    "custas",
    "taxa judiciaria",
    "guia de recolhimento",
    "preparo",
    "dare",
    "gru",
)

_DEPOSIT_FILENAME_BLOCK: tuple[str, ...] = (
    "deposito",
    "dep jud",
    "dep. jud",
    "debito judicial",
    "guia dep",
    "condenacao",
    "condenação",
    "pagamento cond",
)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


def _filename_suggests_court_fees(file_name: str) -> bool:
    normalized = _normalize(file_name)
    if any(keyword in normalized for keyword in _DEPOSIT_FILENAME_BLOCK):
        return False
    return any(keyword in normalized for keyword in _CUSTAS_FILENAME_KEYWORDS)


def path_is_deposit_not_custas(drive_path: str) -> bool:
    if path_suggests_court_fees(drive_path):
        return False
    return path_suggests_deposit_workflow(drive_path)


def should_analyze_pdf(*, drive_path: str, file_name: str) -> bool:
    if should_skip_pdf_by_path_for_custas(drive_path):
        return False
    if path_is_deposit_not_custas(drive_path):
        return False
    if path_suggests_court_fees(drive_path):
        return True
    if not file_name.casefold().endswith(".pdf"):
        return False
    return _filename_suggests_court_fees(file_name)


def custas_document_priority(*, drive_path: str, file_name: str) -> int:
    combined = _normalize(f"{drive_path}/{file_name}")
    if "comprov" in combined:
        return 3
    if "guia" in combined or "recolhimento" in combined:
        return 2
    return 1
