"""Mapeamento de fontes e colunas do board Acessos."""

from __future__ import annotations

import re
import unicodedata

FIELD_LOGIN = "login"
FIELD_PASSWORD = "password"
FIELD_LINK = "link"

FIELD_TITLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    FIELD_LOGIN: ("login",),
    FIELD_PASSWORD: ("senha", "password"),
    FIELD_LINK: ("link", "url", "acesso"),
}

DEFAULT_CREDENTIALS_GROUP_NAME = "procon"

SOURCE_ELEMENTO_ALIASES: dict[str, tuple[str, ...]] = {
    "sp": ("sao paulo", "são paulo", "sp"),
    "proconsumidor": ("proconsumidor",),
    "campinas": ("campinas",),
    "uberlandia": ("uberlandia", "uberlândia"),
    "sjc": ("sao jose dos campos", "são josé dos campos"),
}

DEFAULT_PORTAL_URLS: dict[str, str] = {
    "sp": "https://fornecedor2.procon.sp.gov.br/login",
    "proconsumidor": "https://proconsumidor.mj.gov.br/#/login",
    "campinas": "https://procon.campinas.sp.gov.br/",
    "uberlandia": "https://faleprocon.uberlandia.mg.gov.br/empresas",
}

# Fornecedores a tentar em sequência no Proconsumidor (sem coluna no Monday).
PROCONSUMIDOR_SUPPLIER_LABELS: tuple[str, ...] = (
    "B4A",
    "MMKT",
)


def normalize_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks).strip()


def resolve_field_for_column(title: str) -> str | None:
    normalized = normalize_label(title)
    for field, keywords in FIELD_TITLE_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return field
    return None


def elemento_matches_source(elemento: str, source_id: str) -> bool:
    aliases = SOURCE_ELEMENTO_ALIASES.get(source_id)
    if aliases is None:
        return False
    normalized_elemento = normalize_label(elemento)
    return any(alias in normalized_elemento or normalized_elemento in alias for alias in aliases)


def default_portal_url(source_id: str) -> str | None:
    return DEFAULT_PORTAL_URLS.get(source_id)
