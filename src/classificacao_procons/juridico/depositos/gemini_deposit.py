"""Classificação e extração estruturada via Gemini (PDFs ambíguos)."""

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
from classificacao_procons.juridico.depositos.models import DepositPurpose, DocumentKind


class DepositGeminiError(RuntimeError):
    """Erro na extração estruturada de depósito."""


@dataclass(frozen=True)
class GeminiDepositAnalysis:
    document_kind: DocumentKind
    process_number: str | None
    amount_brl: Decimal | None
    payment_date: str | None
    deposit_purpose: DepositPurpose
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
        raise DepositGeminiError("Gemini não retornou JSON válido.") from exc
    if not isinstance(payload, dict):
        raise DepositGeminiError("Gemini retornou JSON que não é objeto.")
    return payload


def _parse_kind(value: object) -> DocumentKind:
    if not isinstance(value, str):
        return DocumentKind.UNKNOWN
    mapping = {
        "judicial_deposit": DocumentKind.JUDICIAL_DEPOSIT,
        "court_fees": DocumentKind.COURT_FEES,
        "irrelevant": DocumentKind.IRRELEVANT,
        "unknown": DocumentKind.UNKNOWN,
    }
    return mapping.get(value.strip().casefold(), DocumentKind.UNKNOWN)


def _parse_purpose(value: object) -> DepositPurpose:
    if not isinstance(value, str):
        return DepositPurpose.UNKNOWN
    mapping = {
        "condemnation": DepositPurpose.CONDEMNATION,
        "agreement": DepositPurpose.AGREEMENT,
        "guarantee": DepositPurpose.GUARANTEE,
        "consumer_refund": DepositPurpose.CONSUMER_REFUND,
        "unknown": DepositPurpose.UNKNOWN,
    }
    return mapping.get(value.strip().casefold(), DepositPurpose.UNKNOWN)


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


def analyze_deposit_pdf_with_gemini(
    *,
    pdf_path: Path,
    drive_path: str,
    api_key: str | None = None,
    model: str | None = None,
) -> GeminiDepositAnalysis:
    key = api_key or get_api_key_from_env()
    if not key:
        raise DepositGeminiError("GEMINI_API_KEY não configurada.")
    if not pdf_path.exists():
        raise DepositGeminiError(f"PDF não encontrado: {pdf_path}")

    selected_model = model
    if not selected_model:
        available_models = list_generate_content_models(api_key=key)
        selected_model = resolve_gemini_model(
            available_models=available_models,
            preferred=get_model_from_env(),
        )

    prompt = (
        "Você analisa documentos de processos judiciais de consumidor (empresa B4A/glam). "
        "Leia o PDF e responda APENAS com JSON válido (sem markdown), com as chaves:\n"
        "{\n"
        '  "document_kind": "judicial_deposit | court_fees | irrelevant | unknown",\n'
        '  "process_number": "número CNJ ou null",\n'
        '  "amount_brl": "valor principal do depósito/guia em reais (número decimal) ou null",\n'
        '  "payment_date": "YYYY-MM-DD da guia/pagamento ou null",\n'
        '  "deposit_purpose": '
        '"condemnation | agreement | guarantee | consumer_refund | unknown",\n'
        '  "notes": "frase curta justificando a classificação ou null"\n'
        "}\n"
        "Regras:\n"
        "- judicial_deposit: guia ou comprovante de DEPÓSITO JUDICIAL (conta judicial, FUNJECC, "
        "depósito em garantia, pagamento de condenação via depósito). NÃO incluir custas "
        "processuais/taxa judiciária.\n"
        "- court_fees: guias de custas, taxa judiciária, preparo, recolhimento de custas.\n"
        "- irrelevant: entrega de produto, estorno de assinatura, procuração, petição sem "
        "guia/comprovante de depósito.\n"
        "- Não invente valores; use null se não estiver legível.\n"
        f"Caminho no Drive: {drive_path}\n"
    )

    try:
        response = _gemini_request(
            api_key=key,
            model=selected_model,
            parts=[_pdf_part(pdf_path), {"text": prompt}],
        )
    except GeminiClientError as exc:
        raise DepositGeminiError(str(exc)) from exc

    payload = _extract_json_block(response)
    return GeminiDepositAnalysis(
        document_kind=_parse_kind(payload.get("document_kind")),
        process_number=(
            str(payload["process_number"]).strip()
            if payload.get("process_number")
            else None
        ),
        amount_brl=_parse_amount(payload.get("amount_brl")),
        payment_date=(
            str(payload["payment_date"]).strip() if payload.get("payment_date") else None
        ),
        deposit_purpose=_parse_purpose(payload.get("deposit_purpose")),
        notes=str(payload["notes"]).strip() if payload.get("notes") else None,
    )
