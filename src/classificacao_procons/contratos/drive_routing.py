"""Roteamento de contratos assinados para pastas do Google Drive."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from classificacao_procons.contratos.constants import (
    DRIVE_FOLDER_CONTRATOS_ID,
    DRIVE_FOLDER_LOCACAO_ID,
    DRIVE_FOLDER_MINUTAS_ID,
    DRIVE_ROOT_FOLDER_NAMES,
    DRIVE_SUBFOLDER_RH_CLT,
    DRIVE_SUBFOLDER_RH_PJ,
    MINUTAS_SUBFOLDER_BY_CATEGORY,
)

RH_PJ_KEYWORDS: tuple[str, ...] = (
    "contrato pj",
    "prestador pj",
    "pessoa juridica intern",
    "pessoa jurídica intern",
    "contrato de prestacao de servicos pj",
    "contrato de prestação de serviços pj",
)

RH_CLT_KEYWORDS: tuple[str, ...] = (
    "rescisao",
    "rescisão",
    "admissao",
    "admissão",
    "contrato de trabalho",
    "clt",
    "empregado",
    "funcionario",
    "funcionário",
    "holerite",
    "trct",
    "acordo trabalhista",
    "codigo de conduta",
    "código de conduta",
    "codigo de etica",
    "código de ética",
    "ferias",
    "férias",
    "tce",
    "termo de compromisso de estagio",
    "termo de compromisso de estágio",
    "compromisso de estagio",
    "compromisso de estágio",
    "contrato de estagio",
    "contrato de estágio",
    "estagio",
    "estágio",
    "estagiario",
    "estagiário",
    "aviso previo",
    "aviso prévio",
    "homologacao",
    "homologação",
)


@dataclass(frozen=True)
class DriveDestination:
    root_folder_id: str
    path_parts: list[str]


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


def _matches_rh_pj(blob: str) -> bool:
    if any(keyword in blob for keyword in RH_PJ_KEYWORDS):
        return True
    return " pj " in f" {blob} " and "intern" in blob


def _matches_rh_clt(blob: str) -> bool:
    return any(keyword in blob for keyword in RH_CLT_KEYWORDS)


def is_rh_document(*, document_name: str, contract_type: str | None = None) -> bool:
    """Indica se o documento pertence ao fluxo de RH."""
    blob = _normalize_text(f"{document_name} {contract_type or ''}")
    return _matches_rh_pj(blob) or _matches_rh_clt(blob)


def infer_category(*, document_name: str, contract_type: str | None = None) -> str:
    """Infere categoria do contrato a partir do nome e tipo extraído."""
    blob = _normalize_text(f"{document_name} {contract_type or ''}")

    if _matches_rh_pj(blob):
        return "rh_pj"
    if _matches_rh_clt(blob):
        return "rh_clt"

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
    mp_pedido_keywords = ("pedido mp", "pedido marcas proprias", "pedido marcas próprias")
    if any(keyword in blob for keyword in mp_pedido_keywords):
        return "marcas_proprias"
    if "pedido" in blob and any(
        supplier in blob for supplier in ("brass hill", "nobilis", "henlau", "brasshill")
    ):
        return "marcas_proprias"
    return "default"


def infer_monday_tipo(
    *,
    document_name: str,
    category: str,
    contract_type: str | None = None,
) -> str:
    """Mapeia categoria para label Tipo do Monday (Controle Assinaturas / Contratos)."""
    from classificacao_procons.contratos.controle_tipo import classify_controle_tipo_heuristic
    from classificacao_procons.contratos.gemini_extractor import ContractMetadata

    del category  # legado: classificador unificado ignora categoria isolada
    metadata = (
        ContractMetadata(
            counterparty_name=document_name,
            counterparty_cnpj=None,
            contract_type=contract_type,
            company=None,
            start_date=None,
            end_date=None,
            property_name=None,
            summary=None,
        )
        if contract_type
        else None
    )
    result = classify_controle_tipo_heuristic(document_name=document_name, metadata=metadata)
    if result.monday_tipo:
        return result.monday_tipo
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

    if category == "rh_clt":
        return DriveDestination(
            root_folder_id=DRIVE_FOLDER_CONTRATOS_ID,
            path_parts=[DRIVE_SUBFOLDER_RH_CLT, counterparty],
        )

    if category == "rh_pj":
        return DriveDestination(
            root_folder_id=DRIVE_FOLDER_CONTRATOS_ID,
            path_parts=[DRIVE_SUBFOLDER_RH_PJ, counterparty],
        )

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


def format_drive_folder_path(destination: DriveDestination) -> str:
    """Monta caminho legível da pasta no Drive (para logs e resultado do pipeline)."""
    root_name = DRIVE_ROOT_FOLDER_NAMES.get(destination.root_folder_id, "Contratos")
    if not destination.path_parts:
        return root_name
    return " / ".join([root_name, *destination.path_parts])
