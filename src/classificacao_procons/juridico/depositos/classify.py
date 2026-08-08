"""Classificação de documentos pelo texto extraído."""

from __future__ import annotations

import re
import unicodedata

from classificacao_procons.juridico.depositos.models import DepositPurpose, DocumentKind

_DEPOSIT_TEXT_KEYWORDS: tuple[str, ...] = (
    "deposito judicial",
    "depósito judicial",
    "guia de deposito",
    "guia de depósito",
    "conta judicial",
    "deposito em garantia",
    "depósito em garantia",
    "fundo especial dos tribunais",
    "precatorio",
    "precatório",
    "judicial -",
    "dep. jud",
)

_CUSTAS_TEXT_KEYWORDS: tuple[str, ...] = (
    "custas processuais",
    "taxa judiciaria",
    "taxa judiciária",
    "guia de recolhimento",
    "fundesp",
    "dare-sp",
    "custas finais",
    "custas iniciais",
)

_NOISE_TEXT_KEYWORDS: tuple[str, ...] = (
    "comprovante de entrega",
    "rastreamento",
    "jadlog",
    "correios",
    "cancelamento da assinatura",
    "historico de pagamento",
)

_CONDEMNATION_KEYWORDS: tuple[str, ...] = (
    "condenacao",
    "condenação",
    "cumprimento de sentenca",
    "cumprimento de sentença",
    "pagamento da condenacao",
    "pagamento da condenação",
)

_AGREEMENT_KEYWORDS: tuple[str, ...] = (
    "acordo homologado",
    "transacao",
    "transação",
    "homologacao",
    "homologação",
)

_GUARANTEE_KEYWORDS: tuple[str, ...] = (
    "garantia do juizo",
    "garantia do juízo",
    "deposito em garantia",
    "depósito em garantia",
)

_REFUND_KEYWORDS: tuple[str, ...] = (
    "reembolso",
    "restituicao",
    "restituição",
    "devolucao ao consumidor",
    "devolução ao consumidor",
)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


def classify_document_text(text: str) -> DocumentKind:
    normalized = _normalize(text)
    if not normalized:
        return DocumentKind.UNKNOWN
    if any(keyword in normalized for keyword in _NOISE_TEXT_KEYWORDS):
        return DocumentKind.IRRELEVANT
    if any(keyword in normalized for keyword in _CUSTAS_TEXT_KEYWORDS):
        if not any(keyword in normalized for keyword in _DEPOSIT_TEXT_KEYWORDS):
            return DocumentKind.COURT_FEES
    if any(keyword in normalized for keyword in _DEPOSIT_TEXT_KEYWORDS):
        return DocumentKind.JUDICIAL_DEPOSIT
    if "codigo de barras" in normalized and "judicial" in normalized:
        return DocumentKind.JUDICIAL_DEPOSIT
    return DocumentKind.UNKNOWN


def infer_deposit_purpose(*, text: str, drive_path: str) -> DepositPurpose:
    combined = _normalize(f"{drive_path}\n{text}")
    if any(keyword in combined for keyword in _REFUND_KEYWORDS):
        return DepositPurpose.CONSUMER_REFUND
    if any(keyword in combined for keyword in _GUARANTEE_KEYWORDS):
        return DepositPurpose.GUARANTEE
    if any(keyword in combined for keyword in _AGREEMENT_KEYWORDS):
        return DepositPurpose.AGREEMENT
    if any(keyword in combined for keyword in _CONDEMNATION_KEYWORDS):
        return DepositPurpose.CONDEMNATION
    return DepositPurpose.UNKNOWN
