"""Normalização de dados brutos do Questor para os modelos do agente.

Os rótulos de situação e o layout exato variam conforme a versão do Questor e o
órgão emissor; estas funções são tolerantes (comparação sem acento/caixa) para
absorver essas variações. O scraper e o CLI convertem texto do portal ou de um
arquivo JSON em modelos usando estes helpers.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

from classificacao_procons.questor.models import CertidaoStatus


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _fold(value: str) -> str:
    """Minúsculas, sem acento e com espaços colapsados — bom para comparar rótulos."""
    return " ".join(_strip_accents(value).casefold().split())


def normalize_cnpj(value: str | None) -> str | None:
    """Mantém apenas os 14 dígitos do CNPJ; retorna ``None`` se não houver dígitos."""
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return digits or None


def parse_brazilian_date(value: str | None) -> date | None:
    """Interpreta datas ``dd/mm/aaaa`` (ou ``-``) e ISO ``aaaa-mm-dd``."""
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def normalize_situacao(value: str | None) -> CertidaoStatus:
    """Mapeia o texto de situação da certidão para um status canônico.

    Ordem importa: "positiva com efeitos de negativa" deve casar antes de
    "positiva" e de "negativa".
    """
    if not value:
        return "desconhecida"
    folded = _fold(value)
    if not folded:
        return "desconhecida"

    positiva_com_efeitos = (
        "efeito de negativa",
        "efeitos de negativa",
        "positiva com efeito",
        "positiva com efeitos",
        "cpen",
    )
    if any(marker in folded for marker in positiva_com_efeitos):
        return "positiva_com_efeitos_negativa"

    indisponivel = (
        "indisponivel",
        "nao emitida",
        "nao disponivel",
        "sem certidao",
        "erro",
        "falha",
        "pendente de emissao",
    )
    if any(marker in folded for marker in indisponivel):
        return "indisponivel"

    vencida = ("vencida", "expirada", "validade vencida", "prazo expirado")
    if any(marker in folded for marker in vencida):
        return "vencida"

    if "positiva" in folded:
        return "positiva"

    if "negativa" in folded or folded in {"regular", "ok", "valida"}:
        return "negativa"

    return "desconhecida"
