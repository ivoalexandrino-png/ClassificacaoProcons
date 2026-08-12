"""Extração estruturada de custas via Gemini."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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
from classificacao_procons.juridico.custas.classify import infer_fee_type
from classificacao_procons.juridico.custas.models import CourtFeeType


class CustasGeminiError(RuntimeError):
    """Erro na extração estruturada de custas."""


@dataclass(frozen=True)
class GeminiCustasAnalysis:
    is_court_fees: bool
    process_number: str | None
    amount_brl: Decimal | None
    payment_date: str | None
    fee_type: CourtFeeType
    notes: str | None


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
        raise CustasGeminiError("Gemini não retornou JSON válido.") from exc
    if not isinstance(payload, dict):
        raise CustasGeminiError("Gemini retornou JSON que não é objeto.")
    return payload


def _parse_fee_type(value: object, *, text: str, drive_path: str) -> CourtFeeType:
    if not isinstance(value, str):
        return infer_fee_type(text=text, drive_path=drive_path)
    mapping = {
        "initial": CourtFeeType.INITIAL,
        "final": CourtFeeType.FINAL,
        "appeal": CourtFeeType.APPEAL,
        "preparo": CourtFeeType.PREPARO,
        "intimation": CourtFeeType.INTIMATION,
        "other": CourtFeeType.OTHER,
    }
    return mapping.get(value.strip().casefold(), infer_fee_type(text=text, drive_path=drive_path))


def _parse_amount(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if not isinstance(value, str):
        return None
    cleaned = value.strip().replace("R$", "").replace(".", "").replace(",", ".").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def analyze_custas_pdf_with_gemini(
    *,
    pdf_path: Path,
    drive_path: str,
    api_key: str | None = None,
    model: str | None = None,
) -> GeminiCustasAnalysis:
    key = api_key or get_api_key_from_env()
    if not key:
        raise CustasGeminiError("GEMINI_API_KEY não configurada.")
    if not pdf_path.exists():
        raise CustasGeminiError(f"PDF não encontrado: {pdf_path}")

    selected_model = model
    if not selected_model:
        available_models = list_generate_content_models(api_key=key)
        selected_model = resolve_gemini_model(
            available_models=available_models,
            preferred=get_model_from_env(),
        )

    prompt = (
        "Analise o PDF e responda APENAS com JSON válido:\n"
        "{\n"
        '  "is_court_fees": true/false,\n'
        '  "process_number": "CNJ ou null",\n'
        '  "amount_brl": "valor da guia/custas em reais ou null",\n'
        '  "payment_date": "YYYY-MM-DD ou null",\n'
        '  "fee_type": "initial|final|appeal|preparo|intimation|other",\n'
        '  "notes": "frase curta ou null"\n'
        "}\n"
        "is_court_fees=true somente para CUSTAS/TAXA JUDICIÁRIA/PREPARO/GRU/DARE.\n"
        "is_court_fees=false para depósito judicial, condenação, entrega, procuração.\n"
        f"Caminho Drive: {drive_path}\n"
    )

    try:
        response = _gemini_request(
            api_key=key,
            model=selected_model,
            parts=[_pdf_part(pdf_path), {"text": prompt}],
        )
    except GeminiClientError as exc:
        raise CustasGeminiError(str(exc)) from exc

    payload = _extract_json_block(response)
    is_fees = bool(payload.get("is_court_fees"))
    return GeminiCustasAnalysis(
        is_court_fees=is_fees,
        process_number=(
            str(payload["process_number"]).strip() if payload.get("process_number") else None
        ),
        amount_brl=_parse_amount(payload.get("amount_brl")),
        payment_date=(
            str(payload["payment_date"]).strip() if payload.get("payment_date") else None
        ),
        fee_type=_parse_fee_type(
            payload.get("fee_type"),
            text="",
            drive_path=drive_path,
        ),
        notes=str(payload["notes"]).strip() if payload.get("notes") else None,
    )
