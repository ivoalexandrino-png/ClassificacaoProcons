"""Dados cadastrais da reclamada para respostas ao Procon (evita CNPJ inventado pelo LLM)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_CNPJ_PATTERN = re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}")

# Atualize apenas com confirmação jurídica/contábil.
B4A_SERVICOS_CNPJS: frozenset[str] = frozenset(
    {
        "13.475.001/0001-34",
        "13.475.001/0002-15",
        "13.475.001/0003-04",
    },
)

MMKT_CNPJS: frozenset[str] = frozenset(
    {
        "15.481.147/0001-18",
    },
)

B4A_COSMETICS_LEGAL_NAME = "B4A COMÉRCIO DE COSMÉTICOS E SERVIÇOS S.A."


@dataclass(frozen=True)
class _LegalEntityDef:
    entity_id: str
    legal_name: str
    default_cnpj: str
    allowed_cnpjs: frozenset[str]
    headquarters_summary: str
    cnpj_root: str
    name_keywords: tuple[str, ...]


_B4A_SERVICOS = _LegalEntityDef(
    entity_id="b4a",
    legal_name="B4A SERVIÇOS DE TECNOLOGIA E COMÉRCIO S.A.",
    default_cnpj="13.475.001/0001-34",
    allowed_cnpjs=B4A_SERVICOS_CNPJS,
    headquarters_summary=(
        "com sede na Avenida Caio Cotrim, nº 400, Galpão A2, Itaqui, Itapevi/SP, "
        "CEP 06.696-060"
    ),
    cnpj_root="13475001",
    name_keywords=(
        "b4a servicos",
        "b4a serviços",
        "glam clube",
        "glambox",
        "glam ",
    ),
)

_MMKT = _LegalEntityDef(
    entity_id="mmkt",
    legal_name=(
        "MMKT COMÉRCIO DE PRODUTOS DE BELEZA E SERVIÇOS DE CABELEIREIRO LTDA."
    ),
    default_cnpj="15.481.147/0001-18",
    allowed_cnpjs=MMKT_CNPJS,
    headquarters_summary=(
        "com sede na Avenida Portugal, nº 400, Galpão A1, Itaqui, Itapevi/SP, "
        "CEP 06.696-060"
    ),
    cnpj_root="15481147",
    name_keywords=(
        "mmkt",
        "men s market",
        "mens market",
        "men's market",
        "mensmarket",
    ),
)

_ENTITIES: tuple[_LegalEntityDef, ...] = (_B4A_SERVICOS, _MMKT)


@dataclass(frozen=True)
class DefendantLegalProfile:
    legal_name: str
    cnpj: str
    headquarters_summary: str
    allowed_cnpjs: frozenset[str]
    entity_id: str = "b4a"


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


def _entity_for_cnpj(cnpj: str) -> _LegalEntityDef | None:
    root = _normalize_cnpj(cnpj)[:8]
    for entity in _ENTITIES:
        if root == entity.cnpj_root:
            return entity
    return None


def _pick_cnpj_from_complaint(complaint_text: str) -> tuple[_LegalEntityDef, str] | None:
    for cnpj in extract_cnpjs_from_text(complaint_text):
        entity = _entity_for_cnpj(cnpj)
        if entity is not None:
            return entity, cnpj
    return None


def _b4a_legal_name_variant(normalized_complaint: str) -> str:
    if (
        "comercio de cosmeticos" in normalized_complaint
        or "cosmeticos e servicos" in normalized_complaint
    ):
        return B4A_COSMETICS_LEGAL_NAME
    return _B4A_SERVICOS.legal_name


def _profile_from_entity(
    entity: _LegalEntityDef,
    *,
    cnpj: str,
    normalized_complaint: str,
) -> DefendantLegalProfile:
    legal_name = entity.legal_name
    if entity.entity_id == "b4a":
        legal_name = _b4a_legal_name_variant(normalized_complaint)
    return DefendantLegalProfile(
        legal_name=legal_name,
        cnpj=cnpj,
        headquarters_summary=entity.headquarters_summary,
        allowed_cnpjs=entity.allowed_cnpjs,
        entity_id=entity.entity_id,
    )


def _entity_from_keywords(normalized_complaint: str) -> _LegalEntityDef | None:
    for entity in _ENTITIES:
        if any(keyword in normalized_complaint for keyword in entity.name_keywords):
            return entity
    return None


def resolve_defendant_legal_profile(*, complaint_text: str = "") -> DefendantLegalProfile:
    """
    Define razão social e CNPJ da reclamada com base no texto da reclamação.

    Prioridade: CNPJ citado no processo (B4A ou MMKT); depois palavras-chave; senão B4A matriz.
    """
    normalized = _normalize_text(complaint_text)

    from_cnpj = _pick_cnpj_from_complaint(complaint_text)
    if from_cnpj is not None:
        entity, cnpj = from_cnpj
        return _profile_from_entity(entity, cnpj=cnpj, normalized_complaint=normalized)

    from_keywords = _entity_from_keywords(normalized)
    if from_keywords is not None:
        return _profile_from_entity(
            from_keywords,
            cnpj=from_keywords.default_cnpj,
            normalized_complaint=normalized,
        )

    return _profile_from_entity(
        _B4A_SERVICOS,
        cnpj=_B4A_SERVICOS.default_cnpj,
        normalized_complaint=normalized,
    )


def defendant_legal_prompt_block(profile: DefendantLegalProfile) -> str:
    allowed = ", ".join(sorted(profile.allowed_cnpjs))
    return (
        "DADOS CADASTRAIS DA RECLAMADA (use EXCLUSIVAMENTE; "
        "é proibido inventar outro CNPJ ou razão social):\n"
        f"- Razão social: {profile.legal_name}\n"
        f"- CNPJ: {profile.cnpj}\n"
        f"- Sede: {profile.headquarters_summary}\n"
        f"- CNPJs válidos desta reclamada (se precisar citar filial): {allowed}\n"
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
