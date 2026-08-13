"""Transformações explícitas Monday → Sunday por IDs técnicos (não por label).

Mappings canônicos usam (monday_board_id, monday_column_id) → sunday_column_id/key.
Labels servem apenas para documentação e display text de links.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

TransformKind = Literal["status", "file_to_link"]

PROCONS_BOARD_ID = "4944254220"
PROCONS_SUNDAY_BOARD_ID = "82"

# Cancelamento: Monday color_mknz9dwg → Sunday 609 / ouve_cancelamento_de_assinatura
PROCONS_CANCELAMENTO_MONDAY_COLUMN = "color_mknz9dwg"
PROCONS_CANCELAMENTO_SUNDAY_COLUMN = "609"
PROCONS_CANCELAMENTO_SUNDAY_KEY = "ouve_cancelamento_de_assinatura"

# Notificação Procon: Monday arquivos (file) → Sunday 598 (link)
PROCONS_NOTIFICACAO_MONDAY_COLUMN = "arquivos"
PROCONS_NOTIFICACAO_SUNDAY_COLUMN = "598"
PROCONS_NOTIFICACAO_SUNDAY_KEY = "notificacao_procon"
PROCONS_NOTIFICACAO_LINK_TEXT = "Notificação Procon"

# Docs SAC: Monday arquivos8 (file) → Sunday 605 (link)
PROCONS_DOCS_SAC_MONDAY_COLUMN = "arquivos8"
PROCONS_DOCS_SAC_SUNDAY_COLUMN = "605"
PROCONS_DOCS_SAC_SUNDAY_KEY = "docs_sac"
PROCONS_DOCS_SAC_LINK_TEXT = "Docs SAC"


@dataclass(frozen=True)
class ExplicitColumnMapping:
    """Associação técnica source → target independente de label Sunday."""

    monday_board_id: str
    monday_column_id: str
    sunday_board_id: str
    sunday_column_id: str
    sunday_column_key: str | None
    transform: TransformKind
    link_display_text: str | None = None
    documentation_label: str | None = None


EXPLICIT_COLUMN_MAPPINGS: dict[tuple[str, str], ExplicitColumnMapping] = {
    (PROCONS_BOARD_ID, PROCONS_CANCELAMENTO_MONDAY_COLUMN): ExplicitColumnMapping(
        monday_board_id=PROCONS_BOARD_ID,
        monday_column_id=PROCONS_CANCELAMENTO_MONDAY_COLUMN,
        sunday_board_id=PROCONS_SUNDAY_BOARD_ID,
        sunday_column_id=PROCONS_CANCELAMENTO_SUNDAY_COLUMN,
        sunday_column_key=PROCONS_CANCELAMENTO_SUNDAY_KEY,
        transform="status",
        documentation_label="Houve Cancelamento de Assinatura? → Sunday 609",
    ),
    (PROCONS_BOARD_ID, PROCONS_NOTIFICACAO_MONDAY_COLUMN): ExplicitColumnMapping(
        monday_board_id=PROCONS_BOARD_ID,
        monday_column_id=PROCONS_NOTIFICACAO_MONDAY_COLUMN,
        sunday_board_id=PROCONS_SUNDAY_BOARD_ID,
        sunday_column_id=PROCONS_NOTIFICACAO_SUNDAY_COLUMN,
        sunday_column_key=PROCONS_NOTIFICACAO_SUNDAY_KEY,
        transform="file_to_link",
        link_display_text=PROCONS_NOTIFICACAO_LINK_TEXT,
        documentation_label="Notificação Procon file URL → Sunday link 598",
    ),
    (PROCONS_BOARD_ID, PROCONS_DOCS_SAC_MONDAY_COLUMN): ExplicitColumnMapping(
        monday_board_id=PROCONS_BOARD_ID,
        monday_column_id=PROCONS_DOCS_SAC_MONDAY_COLUMN,
        sunday_board_id=PROCONS_SUNDAY_BOARD_ID,
        sunday_column_id=PROCONS_DOCS_SAC_SUNDAY_COLUMN,
        sunday_column_key=PROCONS_DOCS_SAC_SUNDAY_KEY,
        transform="file_to_link",
        link_display_text=PROCONS_DOCS_SAC_LINK_TEXT,
        documentation_label="Docs SAC file URL → Sunday link 605",
    ),
}

PROCONS_REPAIR_MONDAY_COLUMNS: frozenset[str] = frozenset(
    {
        PROCONS_CANCELAMENTO_MONDAY_COLUMN,
        PROCONS_NOTIFICACAO_MONDAY_COLUMN,
        PROCONS_DOCS_SAC_MONDAY_COLUMN,
    },
)


def get_explicit_column_mapping(
    monday_board_id: str,
    monday_column_id: str,
) -> ExplicitColumnMapping | None:
    return EXPLICIT_COLUMN_MAPPINGS.get((monday_board_id, monday_column_id))


def is_file_to_link_mapping(monday_board_id: str, monday_column_id: str) -> bool:
    mapping = get_explicit_column_mapping(monday_board_id, monday_column_id)
    return mapping is not None and mapping.transform == "file_to_link"


def resolve_sunday_column_from_explicit_mapping(
    *,
    monday_board_id: str,
    monday_column_id: str,
    sunday_columns_by_id: dict[str, object],
) -> tuple[str | None, bool]:
    """Resolve sunday_column_id por ID explícito; valida existência no snapshot."""
    mapping = get_explicit_column_mapping(monday_board_id, monday_column_id)
    if mapping is None:
        return None, False
    column = sunday_columns_by_id.get(mapping.sunday_column_id)
    return mapping.sunday_column_id, column is not None


def extract_usable_url(source_text: str | None) -> str | None:
    """Extrai URL utilizável de valor Monday file/link (texto ou JSON)."""
    text = (source_text or "").strip()
    if not text:
        return None
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        if parsed.scheme and parsed.netloc:
            return text
        return None
    return None


def build_sunday_link_value(*, url: str, display_text: str) -> dict[str, str]:
    """Payload PATCH Sunday para coluna type=link: {"url", "text"}."""
    return {"url": url.strip(), "text": display_text}


def derive_file_to_link_value(
    *,
    source_text: str | None,
    display_text: str,
) -> dict[str, str] | None:
    """Monday file URL → Sunday link custom value (LINK_COLUMN_WRITE)."""
    url = extract_usable_url(source_text)
    if not url:
        return None
    return build_sunday_link_value(url=url, display_text=display_text)


def link_values_equal(expected: object, actual: object) -> bool:
    """Compara link Sunday ignorando diferenças irrelevantes de text."""
    if expected == actual:
        return True
    if isinstance(expected, dict) and isinstance(actual, dict):
        return expected.get("url") == actual.get("url")
    if isinstance(actual, dict) and isinstance(expected, str):
        return actual.get("url") == expected
    return False
