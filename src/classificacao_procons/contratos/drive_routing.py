"""Roteamento de contratos assinados para pastas do Google Drive."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from classificacao_procons.contratos.constants import (
    DRIVE_FOLDER_CONTRATOS_ID,
    DRIVE_FOLDER_LOCACAO_ID,
    DRIVE_FOLDER_MINUTAS_ID,
    MINUTAS_SUBFOLDER_BY_CATEGORY,
)


@dataclass(frozen=True)
class DriveDestination:
    root_folder_id: str
    path_parts: list[str]


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


def infer_category(*, document_name: str, contract_type: str | None = None) -> str:
    """Infere categoria do contrato a partir do nome e tipo extraído."""
    blob = _normalize_text(f"{document_name} {contract_type or ''}")

    locacao_keywords = ("locacao", "locação", "imovel", "imóvel", "tower bridge")
    if any(keyword in blob for keyword in locacao_keywords):
        return "locacao"
    if "minuta" in blob:
        if "influencer" in blob or "glamqueen" in blob or "queens" in blob:
            return "influencer"
        mp_keywords = ("marca propria", "marcas proprias", "fornecimento exclusivo")
        if any(keyword in blob for keyword in mp_keywords):
            return "marcas_proprias"
        if "transport" in blob:
            return "transportadora"
        if "consign" in blob:
            return "consignacao"
        if "nda" in blob:
            return "nda"
        if "terceiriz" in blob:
            return "terceirizados"
        if "imagem" in blob or "cessao" in blob:
            return "imagem"
        return "b2b"
    if "influencer" in blob or "glamqueen" in blob:
        return "default"
    if "nda" in blob:
        return "default"
    mp_pedido_keywords = ("pedido mp", "marcas proprias", "nobilis", "brass hill", "henlau")
    if any(keyword in blob for keyword in mp_pedido_keywords):
        return "marcas_proprias"
    return "default"


def infer_monday_tipo(*, document_name: str, category: str) -> str:
    """Mapeia categoria para label Tipo do Monday (Controle Assinaturas / Contratos)."""
    if category == "influencer":
        return "Contratos Influencers (Queens)"
    if category == "nda":
        return "NDA"
    if category == "marcas_proprias":
        return "Pedidos Marcas Próprias"
    if category == "b2b":
        return "Contratos B2B"
    if category == "locacao":
        return "Contratos B4A"

    blob = _normalize_text(document_name)
    if "b2b" in blob:
        return "Contratos B2B"
    if "influencer" in blob:
        return "Contratos Influencers (Queens)"
    if "mmkt" in blob:
        return "Contratos MMKT"
    if "itaro" in blob:
        return "Contratos Itaro"
    if "aurora" in blob:
        return "Contratos Aurora"
    if "rv bvi" in blob or "bvi" in blob:
        return "Contratos RV BVI"
    if "societ" in blob:
        return "Contratos Societários"
    if "cambio" in blob or "câmbio" in document_name.lower():
        return "Contratos de Câmbio"
    return "Contratos B4A"


def _sanitize_folder_part(value: str) -> str:
    cleaned = " ".join(value.split()).strip()
    cleaned = re.sub(r'[\\/:*?"<>|]', "-", cleaned)
    return cleaned[:200] or "Sem nome"


def resolve_drive_destination(
    *,
    document_name: str,
    counterparty_name: str | None,
    contract_type: str | None = None,
    property_name: str | None = None,
) -> DriveDestination:
    """Define pasta de destino no Drive para o PDF assinado."""
    category = infer_category(document_name=document_name, contract_type=contract_type)
    counterparty = _sanitize_folder_part(counterparty_name or document_name)

    if category == "locacao":
        property_folder = _sanitize_folder_part(property_name or counterparty)
        return DriveDestination(
            root_folder_id=DRIVE_FOLDER_LOCACAO_ID,
            path_parts=[property_folder],
        )

    if category in MINUTAS_SUBFOLDER_BY_CATEGORY:
        subfolder = MINUTAS_SUBFOLDER_BY_CATEGORY[category]
        return DriveDestination(
            root_folder_id=DRIVE_FOLDER_MINUTAS_ID,
            path_parts=[subfolder, counterparty],
        )

    if "minuta" in _normalize_text(document_name):
        return DriveDestination(
            root_folder_id=DRIVE_FOLDER_MINUTAS_ID,
            path_parts=[counterparty],
        )

    return DriveDestination(
        root_folder_id=DRIVE_FOLDER_CONTRATOS_ID,
        path_parts=[counterparty],
    )


def build_contract_pdf_filename(*, document_name: str) -> str:
    safe_name = _sanitize_folder_part(document_name)
    if not safe_name.lower().endswith(".pdf"):
        return f"{safe_name}.pdf"
    return safe_name
