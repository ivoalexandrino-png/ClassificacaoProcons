"""Extração de metadados de contratos via Gemini."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from classificacao_procons.gemini.client import (
    GeminiClientError,
    _gemini_request,
    _pdf_part,
    get_api_key_from_env,
    get_model_from_env,
    list_generate_content_models,
    resolve_gemini_model,
)


class ContractExtractionError(RuntimeError):
    """Erro ao extrair metadados do contrato."""


@dataclass(frozen=True)
class ContractMetadata:
    counterparty_name: str
    counterparty_cnpj: str | None
    contract_type: str | None
    company: str | None
    start_date: date | None
    end_date: date | None
    property_name: str | None
    summary: str | None


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            if fmt == "%Y-%m-%d":
                return date.fromisoformat(cleaned)
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _extract_json_block(text: str) -> dict[str, object]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    raw = fenced.group(1) if fenced else text.strip()
    if not raw.startswith("{"):
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractExtractionError("Gemini não retornou JSON válido.") from exc
    if not isinstance(payload, dict):
        raise ContractExtractionError("Gemini retornou JSON que não é objeto.")
    return payload


def extract_contract_metadata(
    *,
    pdf_path: Path,
    document_name: str,
    api_key: str | None = None,
    model: str | None = None,
) -> ContractMetadata:
    """Extrai metadados estruturados de um contrato assinado."""
    key = api_key or get_api_key_from_env()
    if not key:
        raise ContractExtractionError("GEMINI_API_KEY não configurada.")

    if not pdf_path.exists():
        raise ContractExtractionError(f"PDF não encontrado: {pdf_path}")

    selected_model = model
    if not selected_model:
        available_models = list_generate_content_models(api_key=key)
        selected_model = resolve_gemini_model(
            available_models=available_models,
            preferred=get_model_from_env(),
        )

    prompt = (
        "Você é assistente jurídico. Leia o PDF do contrato assinado e retorne APENAS um JSON "
        "válido, sem markdown, com as chaves:\n"
        "{\n"
        '  "counterparty_name": "razão social ou nome da contraparte",\n'
        '  "counterparty_cnpj": "CNPJ ou CPF da contraparte ou null",\n'
        '  "contract_type": "tipo resumido do contrato",\n'
        '  "company": "empresa B4A contratante (B4A, MMKT, Itaro, Aurora, RV BVI ou null)",\n'
        '  "start_date": "YYYY-MM-DD ou null",\n'
        '  "end_date": "YYYY-MM-DD ou null",\n'
        '  "property_name": "nome do imóvel se for locação, senão null",\n'
        '  "summary": "resumo em uma frase"\n'
        "}\n"
        f"Nome do documento no Autentique: {document_name}\n"
        "Use null quando não encontrar o dado. Não invente informações."
    )

    try:
        response = _gemini_request(
            api_key=key,
            model=selected_model,
            parts=[{"text": prompt}, _pdf_part(pdf_path)],
        )
    except GeminiClientError as exc:
        raise ContractExtractionError(str(exc)) from exc

    payload = _extract_json_block(response)
    return ContractMetadata(
        counterparty_name=str(payload.get("counterparty_name") or document_name).strip(),
        counterparty_cnpj=_nullable_str(payload.get("counterparty_cnpj")),
        contract_type=_nullable_str(payload.get("contract_type")),
        company=_nullable_str(payload.get("company")),
        start_date=_parse_iso_date(_nullable_str(payload.get("start_date"))),
        end_date=_parse_iso_date(_nullable_str(payload.get("end_date"))),
        property_name=_nullable_str(payload.get("property_name")),
        summary=_nullable_str(payload.get("summary")),
    )


def _nullable_str(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None
