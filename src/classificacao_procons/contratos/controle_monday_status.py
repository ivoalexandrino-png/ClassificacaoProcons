"""Validação dos rótulos da coluna Status no quadro Controle Assinaturas (Monday)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from classificacao_procons.contratos.constants import (
    CONTROLE_COL_STATUS,
    CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
    CONTROLE_STATUS_AGUARDANDO_OUTROS,
    CONTROLE_STATUS_ASSINADO,
    CONTROLE_STATUS_BLOQUEADO,
    CONTROLE_STATUS_RECUSADO,
    MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
)
from classificacao_procons.monday.client import MondayClientError, load_board_metadata

# Labels que o sync Autentique → Monday pode gravar na coluna Status.
# Rótulos reais no quadro Controle Assinaturas (2026-08); regressão offline.
MONDAY_CONTROLE_STATUS_LABELS_SNAPSHOT: tuple[str, ...] = (
    "Aguardando Assinatura",
    "Aguardando outros",
    "Assinado",
    "Bloqueado - aguardando providencia",
    "Recusado",
)

CONTROLE_STATUS_LABELS_REQUIRED: tuple[str, ...] = (
    CONTROLE_STATUS_AGUARDANDO_ASSINATURA,
    CONTROLE_STATUS_AGUARDANDO_OUTROS,
    CONTROLE_STATUS_ASSINADO,
    CONTROLE_STATUS_RECUSADO,
    CONTROLE_STATUS_BLOQUEADO,
)


@dataclass(frozen=True)
class ControleStatusLabelsReport:
    board_id: str
    status_column_id: str
    status_column_title: str
    monday_labels: tuple[str, ...]
    missing_required_labels: tuple[str, ...]
    ok: bool


def parse_status_column_labels_from_settings(settings_str: str | None) -> tuple[str, ...]:
    """Rótulos da coluna status (case preservado) a partir de ``settings_str`` do Monday."""
    if not settings_str:
        return ()
    try:
        settings = json.loads(settings_str)
    except json.JSONDecodeError:
        return ()
    raw = settings.get("labels", {})
    if not isinstance(raw, dict):
        return ()
    labels = [str(label).strip() for label in raw.values() if str(label).strip()]
    return tuple(sorted(labels, key=str.casefold))


def find_missing_controle_status_labels(
    monday_labels: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    """Rótulos exigidos pelo código que não existem no Monday (comparação case-insensitive)."""
    available = {label.casefold() for label in monday_labels}
    missing: list[str] = []
    for required in CONTROLE_STATUS_LABELS_REQUIRED:
        if required.casefold() not in available:
            missing.append(required)
    return tuple(missing)


def load_controle_status_labels_report(*, api_token: str) -> ControleStatusLabelsReport:
    """Consulta o Monday e valida rótulos da coluna Status do Controle Assinaturas."""
    context = load_board_metadata(
        api_token=api_token,
        board_id=MONDAY_CONTROLE_ASSINATURAS_BOARD_ID,
    )
    status_detail = None
    for detail in context.column_details:
        col = detail.column
        if col.id == CONTROLE_COL_STATUS or col.title.casefold().strip() == "status":
            status_detail = detail
            break
    if status_detail is None:
        raise MondayClientError(
            "Coluna Status não encontrada no quadro Controle Assinaturas "
            f"(board {MONDAY_CONTROLE_ASSINATURAS_BOARD_ID}).",
        )

    monday_labels = parse_status_column_labels_from_settings(status_detail.settings_str)
    missing = find_missing_controle_status_labels(monday_labels)
    return ControleStatusLabelsReport(
        board_id=context.board_id,
        status_column_id=status_detail.column.id,
        status_column_title=status_detail.column.title,
        monday_labels=monday_labels,
        missing_required_labels=missing,
        ok=not missing,
    )
