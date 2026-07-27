"""Dados cadastrais da reclamada para respostas ao Procon (evita CNPJ inventado pelo LLM)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_CNPJ_PATTERN = re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}")

# CNPJs do grupo B4A Serviços de Tecnologia e Comércio S.A. (matriz e filiais).
# Atualize apenas com confirmação jurídica/contábil.
B4A_SERVICOS_CNPJS: frozenset[str] = frozenset(
    {
        "13.475.001/0001-34",
        "13.475.001/0002-15",
        "13.475.001/0003-04",
    },
)

DEFAULT_LEGAL_NAME = "B4A SERVIÇOS DE TECNOLOGIA E COMÉRCIO S.A."
DEFAULT_CNPJ = "13.475.001/0001-34"
DEFAULT_HEADQUARTERS = (
    "com sede na Avenida Caio Cotrim, nº 400, Galpão A2, Itaqui, Itapevi/SP, "
    "CEP 06.696-060"
)


@dataclass(frozen=True)
class DefendantLegalProfile:
    legal_name: str
    cnpj: str
    headquarters_summary: str
    allowed_cnpjs: frozenset[str]


def _normalize_cnpj(value: str) -> str:
    return re.sub(r"\D", "", value)


def _format_cnpj(digits: str) -> str:
    if len(digits) != 14:
        return digits
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:14]}"


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def extract_cnpjs_from_text(text: str) -> list[str]:
    found: list[str] = []
    for match in _CNPJ_PATTERN.finditer(text):
        formatted = _format_cnpj(_normalize_cnpj(match.group(0)))
        if formatted not in found:
            found.append(formatted)
    return found


def _pick_cnpj_from_complaint(complaint_text: str) -> str | None:
    for cnpj in extract_cnpjs_from_text(complaint_text):
        if _normalize_cnpj(cnpj)[:8] == _normalize_cnpj(DEFAULT_CNPJ)[:8]:
            return cnpj
    return None


def resolve_defendant_legal_profile(*, complaint_text: str = "") -> DefendantLegalProfile:
    """
    Define razão social e CNPJ da reclamada com base no texto da reclamação.

    Prioridade: CNPJ do grupo B4A citado no processo; senão matriz padrão.
    """
    cnpj = _pick_cnpj_from_complaint(complaint_text) or DEFAULT_CNPJ
    legal_name = DEFAULT_LEGAL_NAME

    normalized = _normalize_text(complaint_text)
    if "comercio de cosmeticos" in normalized or "cosmeticos e servicos" in normalized:
        legal_name = "B4A COMÉRCIO DE COSMÉTICOS E SERVIÇOS S.A."

    return DefendantLegalProfile(
        legal_name=legal_name,
        cnpj=cnpj,
        headquarters_summary=DEFAULT_HEADQUARTERS,
        allowed_cnpjs=B4A_SERVICOS_CNPJS,
    )


def defendant_legal_prompt_block(profile: DefendantLegalProfile) -> str:
    allowed = ", ".join(sorted(profile.allowed_cnpjs))
    return (
        "DADOS CADASTRAIS DA RECLAMADA (use EXCLUSIVAMENTE; "
        "é proibido inventar outro CNPJ ou razão social):\n"
        f"- Razão social: {profile.legal_name}\n"
        f"- CNPJ: {profile.cnpj}\n"
        f"- Sede: {profile.headquarters_summary}\n"
        f"- CNPJs válidos do grupo (se precisar citar filial): {allowed}\n"
    )


def replace_unauthorized_cnpjs(text: str, *, profile: DefendantLegalProfile) -> str:
    """Substitui CNPJs alucinados pelo CNPJ autorizado do perfil."""
    allowed_digits = {_normalize_cnpj(c) for c in profile.allowed_cnpjs}
    primary = profile.cnpj

    def replacer(match: re.Match[str]) -> str:
        found = match.group(0)
        if _normalize_cnpj(found) in allowed_digits:
            return found
        return primary

    return _CNPJ_PATTERN.sub(replacer, text)
