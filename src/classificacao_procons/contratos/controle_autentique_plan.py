"""Plano Autentique → Controle: classificar antes de criar (CRIAR/VINCULAR/ATUALIZAR/IGNORAR)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from classificacao_procons.contratos.autentique.client import AutentiqueDocumentSummary
from classificacao_procons.contratos.controle_dedup import (
    find_exact_title_matches,
    normalize_controle_title,
    normalized_controle_titles_equal,
)
from classificacao_procons.contratos.controle_legacy_guard import (
    find_legacy_signed_name_matches,
    status_is_assinado,
)
from classificacao_procons.contratos.controle_link_suggestions import (
    _item_has_autentique_link,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import ControleAssinaturasIndex


class ControlePlanAction(StrEnum):
    CRIAR = "criar"
    VINCULAR = "vincular"
    ATUALIZAR = "atualizar"
    IGNORAR = "ignorar"


@dataclass(frozen=True)
class ControleDocumentPlanRow:
    document_id: str
    document_name: str
    action: ControlePlanAction
    autentique_fully_signed: bool
    monday_item_ids: tuple[str, ...]
    monday_item_names: tuple[str, ...]
    reason: str


def _document_id_in_controle_index(document_id: str, index: ControleAssinaturasIndex) -> bool:
    normalized = document_id.casefold().strip()
    if not normalized:
        return False
    if normalized in index.document_ids:
        return True
    return index.get_item(document_id) is not None


def find_legacy_rows_to_link(
    *,
    document: AutentiqueDocumentSummary,
    index: ControleAssinaturasIndex,
) -> tuple[ControleAssinaturasItem, ...]:
    """Linhas Monday **sem** Autentique ID no link com título igual ao documento."""
    without_id = tuple(
        item for item in index.all_items if not _item_has_autentique_link(item, index)
    )
    exact = find_exact_title_matches(document_name=document.name, items=without_id)
    if document.is_fully_signed:
        signed = tuple(item for item in exact if status_is_assinado(item.status))
        if signed:
            return signed
        return find_legacy_signed_name_matches(document_name=document.name, items=without_id)
    return exact


def classify_autentique_document_for_controle(
    *,
    document: AutentiqueDocumentSummary,
    index: ControleAssinaturasIndex,
    import_signed_as_new: bool = False,
) -> ControleDocumentPlanRow:
    """Define a ação correta antes de qualquer write no Monday."""
    doc_id = document.document_id
    linked_items = index.items_for_document_id(doc_id)
    if linked_items or _document_id_in_controle_index(doc_id, index):
        return ControleDocumentPlanRow(
            document_id=doc_id,
            document_name=document.name,
            action=ControlePlanAction.ATUALIZAR,
            autentique_fully_signed=document.is_fully_signed,
            monday_item_ids=tuple(item.item_id for item in linked_items),
            monday_item_names=tuple(item.name for item in linked_items),
            reason="autentique_id_already_on_monday",
        )

    link_targets = find_legacy_rows_to_link(document=document, index=index)
    if link_targets:
        expected_title = normalize_controle_title(document.name)
        if any(normalize_controle_title(item.name) != expected_title for item in link_targets):
            return ControleDocumentPlanRow(
                document_id=doc_id,
                document_name=document.name,
                action=ControlePlanAction.IGNORAR,
                autentique_fully_signed=document.is_fully_signed,
                monday_item_ids=tuple(item.item_id for item in link_targets),
                monday_item_names=tuple(item.name for item in link_targets[:5]),
                reason="ambiguous_legacy_match_manual_link",
            )
        return ControleDocumentPlanRow(
            document_id=doc_id,
            document_name=document.name,
            action=ControlePlanAction.VINCULAR,
            autentique_fully_signed=document.is_fully_signed,
            monday_item_ids=tuple(item.item_id for item in link_targets),
            monday_item_names=tuple(item.name for item in link_targets),
            reason="legacy_row_without_id_exact_title",
        )

    if document.is_fully_signed:
        if import_signed_as_new:
            return ControleDocumentPlanRow(
                document_id=doc_id,
                document_name=document.name,
                action=ControlePlanAction.CRIAR,
                autentique_fully_signed=True,
                monday_item_ids=(),
                monday_item_names=(),
                reason="import_signed_as_new_explicit",
            )
        return ControleDocumentPlanRow(
            document_id=doc_id,
            document_name=document.name,
            action=ControlePlanAction.IGNORAR,
            autentique_fully_signed=True,
            monday_item_ids=(),
            monday_item_names=(),
            reason="signed_no_matching_legacy_row",
        )

    return ControleDocumentPlanRow(
        document_id=doc_id,
        document_name=document.name,
        action=ControlePlanAction.CRIAR,
        autentique_fully_signed=False,
        monday_item_ids=(),
        monday_item_names=(),
        reason="pending_no_monday_row",
    )


def build_controle_autentique_plan(
    *,
    documents: tuple[AutentiqueDocumentSummary, ...] | list[AutentiqueDocumentSummary],
    index: ControleAssinaturasIndex,
    import_signed_as_new: bool = False,
) -> tuple[ControleDocumentPlanRow, ...]:
    return tuple(
        classify_autentique_document_for_controle(
            document=document,
            index=index,
            import_signed_as_new=import_signed_as_new,
        )
        for document in documents
    )


def plan_action_counts(rows: tuple[ControleDocumentPlanRow, ...]) -> dict[str, int]:
    counts: dict[str, int] = {action.value: 0 for action in ControlePlanAction}
    for row in rows:
        counts[row.action.value] += 1
    return counts


def legacy_title_match_without_id(
    *,
    document_name: str,
    index: ControleAssinaturasIndex,
) -> bool:
    """True quando já existe linha com título equivalente mas sem ID (deve VINCULAR, não criar)."""
    without_id = [
        item for item in index.all_items if not _item_has_autentique_link(item, index)
    ]
    for item in without_id:
        if normalized_controle_titles_equal(document_name, item.name):
            return True
    return False
