"""Classificação da coluna Tipo (Controle Assinaturas) — heurísticas + Gemini no PDF."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from classificacao_procons.contratos.constants import (
    MONDAY_CONTROLE_TIPO_LABELS,
    MONDAY_TIPO_RH,
)
from classificacao_procons.contratos.contratos_routing import is_supplemental_document
from classificacao_procons.contratos.drive_routing import (
    _matches_rh_clt,
    _matches_rh_pj,
    _normalize_text,
    is_rh_document,
)
from classificacao_procons.contratos.gemini_extractor import (
    ContractExtractionError,
    ContractMetadata,
)

Confidence = Literal["high", "medium", "low"]

# Labels exatos da coluna Tipo no Monday (Controle Assinaturas).
MONDAY_TIPO_LABELS = MONDAY_CONTROLE_TIPO_LABELS

ENTITY_TO_TIPO: dict[str, str] = {
    "b4a": "Contratos B4A",
    "mmkt": "Contratos MMKT",
    "itaro": "Contratos Itaro",
    "aurora": "Contratos Aurora",
    "rv bvi": "Contratos RV BVI",
    "rvbvi": "Contratos RV BVI",
}

SOCIETARIO_KEYWORDS: tuple[str, ...] = (
    "stock option",
    "opcao de compra",
    "opção de compra",
    "convertible note",
    "nota conversivel",
    "nota conversível",
    "tokeniz",
    "token ",
    "4equity",
    "4 equity",
    "acordo de socios",
    "acordo de sócios",
    "shareholder",
    "quotas",
    "cessao onerosa de participacao",
    "cessão onerosa de participação",
    "mútuo conversivel",
    "mutuo conversivel",
    "mútuo conversível",
    "mutuo conversível",
)

MP_ORDER_KEYWORDS: tuple[str, ...] = (
    "pedido brass hill",
    "pedido mp",
    "pedido conforto",
    "pedido nobilis",
    "pedido henlau",
    "pedido marcas proprias",
    "pedido marcas próprias",
)

# Fornecedores MP: B2B, pedido ou B4A — não inferir só pelo nome.
MP_SUPPLIER_NAME_MARKERS: tuple[str, ...] = (
    "brass hill",
    "brasshill",
    "nobilis",
    "henlau",
    "glam nutri wiki",
)

MP_CONTRACT_KEYWORDS: tuple[str, ...] = (
    "fornecimento exclusivo",
    "marca propria",
    "marcas proprias",
    "marca própria",
    "marcas próprias",
)

NDA_KEYWORDS: tuple[str, ...] = (
    "nda",
    "non-disclosure",
    "non disclosure",
    "acordo de confidencialidade",
    "confidentiality agreement",
    "termo de confidencialidade",
)

INFLUENCER_KEYWORDS: tuple[str, ...] = (
    "influencer",
    "influenciadora",
    "glamqueen",
    "queens",
    "campanha",
    "postagem",
)

B2B_KEYWORDS: tuple[str, ...] = (
    "minuta padrao",
    "minuta padrão",
    "contrato parceria",
    "parceria b2b",
    "proposta comercial",
    "contrato b2b",
)

JAN_PF_KEYWORDS: tuple[str, ...] = (
    "jan riehle",
    "jan r riehle",
    "contrato jan ",
    "firmado por jan",
)

FOUR_EQUITY_INTERCO_KEYWORDS: tuple[str, ...] = (
    "codemp",
    "servicos",
    "serviços",
    "prestacao de servicos",
    "prestação de serviços",
    "bvi-b4a",
    "b4a servicos",
)

B2B_PARTNER_MARKERS: tuple[str, ...] = (
    "korres",
    "bfluence",
    "abelha rainha",
)

CESSAO_ESPACO_B4A_MARKERS: tuple[str, ...] = (
    "cessao onerosa espaco",
    "cessão onerosa espaço",
    "purodigital",
)


@dataclass(frozen=True)
class TipoClassificationResult:
    monday_tipo: str | None
    confidence: Confidence
    source: Literal["heuristic", "gemini", "metadata"]
    rationale: str


def _blob(document_name: str, metadata: ContractMetadata | None) -> str:
    parts = [document_name]
    if metadata:
        if metadata.contract_type:
            parts.append(metadata.contract_type)
        if metadata.company:
            parts.append(metadata.company)
        if metadata.summary:
            parts.append(metadata.summary)
    return _normalize_text(" ".join(parts))


def _is_confidentiality_primary(blob: str) -> bool:
    if not any(k in blob for k in NDA_KEYWORDS):
        return False
    b2b_markers = (
        "parceria",
        "fornecimento",
        "prestacao de servicos",
        "prestação de serviços",
        "locacao",
    )
    if any(m in blob for m in b2b_markers) and "nda" not in blob.split()[0:3]:
        return "acordo de confidencialidade" in blob or blob.strip().startswith("nda")
    return True


def _is_unambiguous_mp_order(blob: str) -> bool:
    if re.search(r"\bpedido\b", blob):
        return True
    return any(k in blob for k in MP_ORDER_KEYWORDS)


def _mentions_mp_supplier_name(blob: str) -> bool:
    return any(marker in blob for marker in MP_SUPPLIER_NAME_MARKERS)


def _is_ambiguous_prestacao_servicos(blob: str) -> bool:
    if "prestacao de servicos" not in blob and "prestação de serviços" not in blob:
        return False
    if "pj interno" in blob or "contrato pj" in blob:
        return False
    corporate_markers = (
        "ltda",
        " ltda",
        " s.a",
        " s/a",
        " eireli",
        " holding",
        " comercio",
        " comércio",
        " industria",
        " indústria",
        " consultoria",
        " comunidade",
        " bianco",
    )
    if any(marker in blob for marker in corporate_markers):
        return False
    return True


def supplier_title_requires_pdf_analysis(
    *,
    document_name: str,
    metadata: ContractMetadata | None = None,
) -> bool:
    """Título cita fornecedor MP sem objeto claro (pedido vs parceria vs B4A)."""
    blob = _blob(document_name, metadata)
    if not _mentions_mp_supplier_name(blob):
        return False
    if _is_unambiguous_mp_order(blob):
        return False
    if any(k in blob for k in B2B_KEYWORDS) or "b2b" in blob:
        return False
    if _is_mp_supply_contract(blob):
        return False
    if _is_confidentiality_primary(blob):
        return False
    return True


def needs_document_content_for_tipo_commit(
    *,
    document_name: str,
    metadata: ContractMetadata | None = None,
) -> bool:
    """True quando o Tipo não deve ser gravado só com base no título (priorizar PDF)."""
    blob = _blob(document_name, metadata)
    if _is_controle_internal_document(blob):
        return False
    if is_rh_document(
        document_name=document_name,
        contract_type=metadata.contract_type if metadata else None,
    ):
        return False
    if _is_confidentiality_primary(blob):
        return False
    if _is_unambiguous_mp_order(blob):
        return False
    if metadata and metadata.company:
        return False
    if _is_ambiguous_pj_externo(blob):
        return True
    if supplier_title_requires_pdf_analysis(document_name=document_name, metadata=metadata):
        return True
    if _is_ambiguous_prestacao_servicos(blob):
        return True
    return True


def document_requires_pdf_analysis(
    *,
    document_name: str,
    metadata: ContractMetadata | None = None,
) -> bool:
    """Título insuficiente: exige leitura do PDF (Gemini) antes de gravar Tipo."""
    return needs_document_content_for_tipo_commit(
        document_name=document_name,
        metadata=metadata,
    )


def _is_controle_internal_document(blob: str) -> bool:
    """Sem coluna Tipo no Controle (documentos internos ou tipo só no quadro Contratos)."""
    if "requerimento de parcelamento" in blob:
        return True
    if "circularizacao" in blob and ("fornecedor" in blob or "advogado" in blob):
        return True
    if "cambio" in blob:
        return True
    return False


def _is_mp_supplier_fornecimento_exclusivo_b4a(blob: str) -> bool:
    if not any(k in blob for k in MP_CONTRACT_KEYWORDS):
        return False
    return _mentions_mp_supplier_name(blob)


def _is_cessao_espaco_b4a(blob: str) -> bool:
    if "cessao onerosa" in blob or "cessão onerosa" in blob:
        if "participacao" in blob or "participação" in blob or "societaria" in blob:
            return False
        if any(m in blob for m in CESSAO_ESPACO_B4A_MARKERS):
            return True
        if "espaco" in blob or "espaço" in blob:
            return True
    return False


def _is_ambiguous_pj_externo(blob: str) -> bool:
    if "contrato pj" not in blob and "prestador" not in blob:
        return False
    if "interno" in blob or "pj interno" in blob:
        return False
    return "prestador" in blob or "marketing" in blob


def _is_mp_order(blob: str) -> bool:
    return _is_unambiguous_mp_order(blob)


def _is_mp_supply_contract(blob: str) -> bool:
    return any(k in blob for k in MP_CONTRACT_KEYWORDS) and not _is_mp_order(blob)


def _is_societario(blob: str) -> bool:
    if "4equity" in blob or "4 equity" in blob:
        return False
    return any(
        k in blob
        for k in SOCIETARIO_KEYWORDS
        if k not in ("4equity", "4 equity")
    )


def _classify_four_equity(
    blob: str,
    metadata: ContractMetadata | None,
) -> TipoClassificationResult | None:
    if "4equity" not in blob and "4 equity" not in blob:
        return None
    if _is_societario(blob):
        return TipoClassificationResult(
            monday_tipo="Contratos Societários",
            confidence="high",
            source="heuristic",
            rationale="4Equity com objeto societário (equity/token/opções/quotas).",
        )
    if _is_aditivo_blob(blob):
        return TipoClassificationResult(
            monday_tipo="Contratos Societários",
            confidence="high",
            source="heuristic",
            rationale="Aditivo 4Equity segue contrato societário principal.",
        )
    if any(k in blob for k in FOUR_EQUITY_INTERCO_KEYWORDS):
        return TipoClassificationResult(
            monday_tipo="Contratos Societários",
            confidence="high",
            source="heuristic",
            rationale=(
                "4Equity intercompany (ex. BVI-B4A/CODEMP): contrato societário do grupo."
            ),
        )
    return TipoClassificationResult(
        monday_tipo="Contratos Societários",
        confidence="medium",
        source="heuristic",
        rationale="Documento 4Equity sem sinal de pedido/serviço operacional — padrão societário.",
    )


def _resolve_entity_from_metadata(metadata: ContractMetadata | None) -> str | None:
    if not metadata or not metadata.company:
        return None
    normalized = _normalize_text(metadata.company)
    for key in ENTITY_TO_TIPO:
        if key in normalized:
            return key
    return None


def _resolve_entity_fallback(blob: str) -> str:
    if "mmkt" in blob:
        return "mmkt"
    if "itaro" in blob:
        return "itaro"
    if "aurora" in blob:
        return "aurora"
    if "rv bvi" in blob or re.search(r"\brv\s*bvi\b", blob):
        return "rv bvi"
    return "b4a"


def _is_jan_pf_contract(blob: str, metadata: ContractMetadata | None) -> bool:
    if any(k in blob for k in JAN_PF_KEYWORDS):
        if not any(e in blob for e in ("b4a", "mmkt", "itaro", "aurora", "beauty for all")):
            return True
    if metadata and metadata.company:
        company = _normalize_text(metadata.company)
        if company in {"jan", "jan pf", "pessoa fisica", "pessoa física"}:
            return True
    return False


def _is_aditivo_blob(blob: str) -> bool:
    return any(
        marker in blob
        for marker in (
            "aditivo",
            "termo aditivo",
            "distrato",
            "anexo",
            "prorrogacao",
            "prorrogação",
            "renovacao",
            "renovação",
        )
    )


def _is_accessory_document(
    *,
    document_name: str,
    metadata: ContractMetadata | None,
) -> bool:
    if metadata is not None and metadata.is_supplemental is True:
        return True
    if metadata is not None and metadata.is_supplemental is False:
        return False
    return _is_aditivo_blob(_blob(document_name, metadata))


def _derive_principal_document_title(
    *,
    document_name: str,
    metadata: ContractMetadata | None,
) -> str | None:
    if metadata and metadata.parent_contract_reference:
        cleaned = metadata.parent_contract_reference.strip()
        if cleaned:
            return cleaned

    stripped = document_name.strip()
    patterns = (
        r"^(?:\d+º\s+)?termo\s+aditivo\s*[-–:]\s*",
        r"^(?:\d+º\s+)?aditivo\s*[-–:]\s*",
        r"^aditivo\s+(?:ao|à|a)\s+(?:contrato\s+)?",
        r"^distrato\s*[-–:]\s*",
        r"^anexo\s*[-–:]\s*",
    )
    for pattern in patterns:
        candidate = re.sub(pattern, "", stripped, count=1, flags=re.IGNORECASE).strip()
        if candidate and candidate.casefold() != stripped.casefold() and len(candidate) >= 8:
            return candidate
    return None


def classify_accessory_follows_principal(
    *,
    document_name: str,
    metadata: ContractMetadata | None = None,
) -> TipoClassificationResult | None:
    """Regra acessório segue o principal (aditivo/anexo herda Tipo do contrato base)."""
    if not _is_accessory_document(document_name=document_name, metadata=metadata):
        return None

    blob = _blob(document_name, metadata)
    if ("4equity" in blob or "4 equity" in blob) and _is_aditivo_blob(blob):
        return TipoClassificationResult(
            monday_tipo="Contratos Societários",
            confidence="high",
            source="heuristic",
            rationale=(
                "Aditivo 4Equity: acessório segue contrato societário principal "
                "(ecossistema 4Equity)."
            ),
        )

    if _is_aditivo_blob(blob) and any(m in blob for m in B2B_PARTNER_MARKERS):
        return TipoClassificationResult(
            monday_tipo="Contratos B2B",
            confidence="high",
            source="heuristic",
            rationale="Aditivo a contrato de parceria B2B (ex. Korres/Bfluence).",
        )

    principal_title = _derive_principal_document_title(
        document_name=document_name,
        metadata=metadata,
    )
    if not principal_title:
        return None

    principal = classify_controle_tipo_heuristic(
        document_name=principal_title,
        metadata=None,
        skip_pdf_requirement=True,
    )
    if not principal.monday_tipo:
        return None
    confidence: Confidence = "high" if principal.confidence == "high" else "medium"
    return TipoClassificationResult(
        monday_tipo=principal.monday_tipo,
        confidence=confidence,
        source="heuristic",
        rationale=f"Acessório segue contrato principal: {principal_title[:80]}.",
    )


def should_omit_controle_tipo(
    *,
    document_name: str,
    metadata: ContractMetadata | None = None,
) -> bool:
    """Documentos complementares sem categoria RH explícita ficam sem Tipo (subitem/pai)."""
    if classify_accessory_follows_principal(document_name=document_name, metadata=metadata):
        return False
    blob = _blob(document_name, metadata)
    if _is_controle_internal_document(blob):
        return True
    if _matches_rh_pj(blob) or _matches_rh_clt(blob):
        if "aditivo" in blob or "distrato" in blob:
            return False
    if "aditivo" in blob and ("4equity" in blob or "4 equity" in blob):
        return False
    if metadata and metadata.is_supplemental is True:
        if is_rh_document(document_name=document_name, contract_type=metadata.contract_type):
            return False
        return True
    if is_supplemental_document(document_name=document_name, metadata=metadata):
        if is_rh_document(
            document_name=document_name,
            contract_type=metadata.contract_type if metadata else None,
        ):
            return False
        return True
    return False


def classify_controle_tipo_heuristic(
    *,
    document_name: str,
    metadata: ContractMetadata | None = None,
    skip_pdf_requirement: bool = False,
) -> TipoClassificationResult:
    inherited = classify_accessory_follows_principal(
        document_name=document_name,
        metadata=metadata,
    )
    if inherited:
        return inherited

    blob = _blob(document_name, metadata)

    if _is_controle_internal_document(blob):
        return TipoClassificationResult(
            monday_tipo=None,
            confidence="high",
            source="heuristic",
            rationale="Documento interno ou tipo só no quadro Contratos (sem Tipo no Controle).",
        )

    if _is_cessao_espaco_b4a(blob):
        return TipoClassificationResult(
            monday_tipo="Contratos B4A",
            confidence="high",
            source="heuristic",
            rationale="Cessão onerosa de espaço (operacional B4A).",
        )

    if "abelha rainha" in blob:
        return TipoClassificationResult(
            monday_tipo="Contratos B2B",
            confidence="high",
            source="heuristic",
            rationale="Contrato de parceria B2B (fornecedor Abelha Rainha).",
        )

    if _is_ambiguous_pj_externo(blob):
        return TipoClassificationResult(
            monday_tipo=None,
            confidence="low",
            source="heuristic",
            rationale="Contrato PJ externo: distinguir RH (PJ interno) vs B2B pelo PDF.",
        )

    if is_rh_document(
        document_name=document_name,
        contract_type=metadata.contract_type if metadata else None,
    ):
        return TipoClassificationResult(
            monday_tipo=MONDAY_TIPO_RH,
            confidence="high",
            source="heuristic",
            rationale=(
                "Colaborador/PJ interno, rescisão, TCE, férias, "
                "código de conduta ou equivalente."
            ),
        )

    if _is_confidentiality_primary(blob):
        return TipoClassificationResult(
            monday_tipo="NDA",
            confidence="high",
            source="heuristic",
            rationale="Acordo de confidencialidade como objeto principal.",
        )

    if _is_mp_order(blob):
        return TipoClassificationResult(
            monday_tipo="Pedidos Marcas Próprias",
            confidence="high",
            source="heuristic",
            rationale="Pedido a fornecedor de produto com marca própria.",
        )

    if _is_mp_supplier_fornecimento_exclusivo_b4a(blob):
        return TipoClassificationResult(
            monday_tipo="Contratos B4A",
            confidence="high",
            source="heuristic",
            rationale="Fornecimento exclusivo com fornecedor MP (Nobilis/Brass Hill) como B4A.",
        )

    if _is_mp_supply_contract(blob):
        return TipoClassificationResult(
            monday_tipo="Contratos B2B",
            confidence="medium",
            source="heuristic",
            rationale="Contrato de fornecimento exclusivo/marcas (não pedido pontual).",
        )

    four_eq = _classify_four_equity(blob, metadata)
    if four_eq:
        return four_eq

    if _is_societario(blob):
        return TipoClassificationResult(
            monday_tipo="Contratos Societários",
            confidence="high",
            source="heuristic",
            rationale="Tokenização, stock options, convertible ou impacto societário.",
        )

    if any(k in blob for k in INFLUENCER_KEYWORDS):
        return TipoClassificationResult(
            monday_tipo="Contratos Influencers (Queens)",
            confidence="high",
            source="heuristic",
            rationale="Contrato com influencer/campanha.",
        )

    if _is_jan_pf_contract(blob, metadata):
        return TipoClassificationResult(
            monday_tipo="Contratos Jan",
            confidence="medium",
            source="heuristic",
            rationale="Contrato em pessoa física Jan, sem vínculo B4A/MMKT/Itaro/Aurora no título.",
        )

    if any(k in blob for k in B2B_KEYWORDS) or "b2b" in blob:
        return TipoClassificationResult(
            monday_tipo="Contratos B2B",
            confidence="high",
            source="heuristic",
            rationale="Minuta padrão de parceria ou proposta comercial B2B.",
        )

    if not skip_pdf_requirement and document_requires_pdf_analysis(
        document_name=document_name,
        metadata=metadata,
    ):
        return TipoClassificationResult(
            monday_tipo=None,
            confidence="low",
            source="heuristic",
            rationale=(
                "Título ambíguo (fornecedor MP, prestação de serviços PJ/B2B, etc.) — "
                "classificar pelo conteúdo do PDF."
            ),
        )

    entity_key = _resolve_entity_from_metadata(metadata) or _resolve_entity_fallback(blob)
    if entity_key == "rv bvi" and "bvi-b4a" not in blob and "4equity" not in blob:
        return TipoClassificationResult(
            monday_tipo="Contratos RV BVI",
            confidence="medium",
            source="heuristic",
            rationale="Contratante RV BVI (não apenas menção BVI em estrutura 4Equity).",
        )

    if entity_key in ENTITY_TO_TIPO:
        return TipoClassificationResult(
            monday_tipo=ENTITY_TO_TIPO[entity_key],
            confidence="medium",
            source="heuristic",
            rationale=f"Regra geral por entidade ({entity_key.upper()}).",
        )

    return TipoClassificationResult(
        monday_tipo="Contratos B4A",
        confidence="low",
        source="heuristic",
        rationale="Fallback B4A — recomenda-se validação com PDF/Gemini.",
    )


def _build_gemini_tipo_prompt(*, document_name: str) -> str:
    labels = ", ".join(sorted(MONDAY_TIPO_LABELS))
    return (
        "Você classifica contratos da Beauty For All para a coluna Tipo do Monday.\n"
        f"monday_tipo deve ser um destes (ou null): {labels}.\n\n"
        "O título do Autentique é apenas pista — a classificação deve vir do CONTEÚDO do PDF "
        "(partes, objeto, cláusulas). Ignore palavras enganosas no título (MMKT, B4A, "
        "nome de fornecedor) se o contrato disser outra coisa.\n\n"
        "Regras (ordem de prioridade):\n"
        "1. RH: colaboradores, CLT, rescisão, TCE, estágio, férias, códigos de conduta, "
        "contratos e aditivos de PJ INTERNOS (prestação para a B4A como colaborador).\n"
        "2. NDA: acordo de confidencialidade como OBJETO principal (não cláusula em parceria).\n"
        "3. Pedidos MP: pedido de produção/compra com nossa marca. "
        "Não use só o nome do fornecedor (Brass Hill, Nobilis): pode ser B2B, MP ou B4A.\n"
        "4. Contratos Societários: tokenização, stock options, convertible notes, 4Equity, "
        "acordos de quotas/sócios, cessão onerosa de participação societária.\n"
        "5. Contratos Influencers (Queens): campanhas com influencers.\n"
        "6. Contratos Jan: PF Jan, sem B4A/MMKT/Itaro/Aurora como contratante.\n"
        "7. Contratos B2B: parcerias/minutas padrão ou propostas comerciais "
        "(fornecedor externo, não PJ interno RH).\n"
        "8. Senão: MMKT, Itaro, Aurora, RV BVI ou B4A pela PARTE CONTRATANTE no PDF.\n"
        "9. 4Equity: equity/token → Societários; aditivo intercompany "
        "(BVI-B4A, CODEMP) → B4A salvo outra contratante.\n"
        "10. NÃO use Contratos RV BVI só porque aparece 'BVI' no nome (ex. 4Equity x BVI-B4A).\n"
        "11. Aditivos/distratos que só alteram contrato RH/PJ interno → monday_tipo RH.\n"
        "12. Aditivos/anexos: mesmo monday_tipo do contrato principal.\n"
        "13. Aditivo 4Equity a contrato societário → Contratos Societários.\n"
        "14. Aditivos B2B/societários sem tipo novo → null se o principal não for identificável.\n"
        "15. Leia o PDF: objeto do contrato prevalece sobre o nome do fornecedor no título.\n"
        "16. Documentos internos (circularização de fornecedores ou advogados, "
        "requerimento de parcelamento, câmbio) → monday_tipo null "
        "(sem Tipo no Controle; roteamento no quadro Contratos quando aplicável).\n"
        f"Nome no Autentique: {document_name}\n"
    )


def _parse_tipo_json(text: str) -> dict[str, object]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    raw = fenced.group(1) if fenced else text.strip()
    if not raw.startswith("{"):
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ContractExtractionError("Classificador não retornou objeto JSON.")
    return payload


def classify_controle_tipo_with_gemini(
    *,
    pdf_path: Path,
    document_name: str,
    api_key: str | None = None,
    model: str | None = None,
) -> TipoClassificationResult:
    from classificacao_procons.contratos.gemini_extractor import extract_contract_metadata
    from classificacao_procons.gemini.client import (
        _gemini_request,
        _pdf_part,
        get_api_key_from_env,
        get_model_from_env,
        list_generate_content_models,
        resolve_gemini_model,
    )

    key = api_key or get_api_key_from_env()
    if not key:
        raise ContractExtractionError("GEMINI_API_KEY não configurada.")

    metadata = extract_contract_metadata(
        pdf_path=pdf_path,
        document_name=document_name,
        api_key=key,
        model=model,
    )

    selected_model = model
    if not selected_model:
        available = list_generate_content_models(api_key=key)
        selected_model = resolve_gemini_model(
            available_models=available,
            preferred=get_model_from_env(),
        )

    prompt = _build_gemini_tipo_prompt(document_name=document_name)
    context = (
        f"Metadados já extraídos: company={metadata.company}, "
        f"contract_type={metadata.contract_type}, summary={metadata.summary}, "
        f"is_supplemental={metadata.is_supplemental}\n"
    )

    response = _gemini_request(
        api_key=key,
        model=selected_model,
        parts=[{"text": prompt + context}, _pdf_part(pdf_path)],
    )
    payload = _parse_tipo_json(response)
    tipo = payload.get("monday_tipo")
    tipo_str = str(tipo).strip() if tipo else None
    if tipo_str and tipo_str not in MONDAY_TIPO_LABELS:
        tipo_str = None
    conf_raw = str(payload.get("confidence") or "low").strip().lower()
    confidence: Confidence = conf_raw if conf_raw in ("high", "medium", "low") else "low"
    rationale = str(payload.get("rationale") or "Classificação Gemini.").strip()
    return TipoClassificationResult(
        monday_tipo=tipo_str,
        confidence=confidence,
        source="gemini",
        rationale=rationale,
    )


def resolve_controle_tipo_label(
    *,
    document_name: str,
    metadata: ContractMetadata | None = None,
    pdf_path: Path | None = None,
    gemini_api_key: str | None = None,
    skip_gemini: bool = False,
    min_confidence: Confidence = "medium",
) -> str | None:
    """Define o label Tipo para o Controle (None = deixar em branco / suplementar).

    Política: título só grava Tipo em casos explícitos (RH, NDA, pedido MP, internos).
    Demais casos exigem análise do PDF; com PDF presente, só a classificação Gemini grava Tipo.
    """
    inherited = classify_accessory_follows_principal(
        document_name=document_name,
        metadata=metadata,
    )
    if inherited and inherited.monday_tipo:
        return inherited.monday_tipo

    if should_omit_controle_tipo(document_name=document_name, metadata=metadata):
        return None

    heuristic = classify_controle_tipo_heuristic(document_name=document_name, metadata=metadata)
    has_pdf = pdf_path is not None and pdf_path.exists()
    rank = {"high": 3, "medium": 2, "low": 1}

    if has_pdf and not skip_gemini:
        try:
            gemini = classify_controle_tipo_with_gemini(
                pdf_path=pdf_path,
                document_name=document_name,
                api_key=gemini_api_key,
            )
        except ContractExtractionError:
            return None
        if gemini.monday_tipo and rank[gemini.confidence] >= rank[min_confidence]:
            return gemini.monday_tipo
        return None

    if needs_document_content_for_tipo_commit(
        document_name=document_name,
        metadata=metadata,
    ):
        return None

    if heuristic.monday_tipo is None:
        return None

    if heuristic.confidence == "low" and min_confidence != "low":
        return None
    return heuristic.monday_tipo


def map_metadata_company_to_tipo(company: str | None) -> str | None:
    if not company:
        return None
    key = _normalize_text(company)
    for entity, tipo in ENTITY_TO_TIPO.items():
        if entity in key:
            return tipo
    return None
