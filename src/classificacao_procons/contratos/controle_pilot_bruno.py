"""Piloto Controle: distrato Bruno v2 — criação e reconcile sem sync em massa."""

from __future__ import annotations

from dataclasses import dataclass

from classificacao_procons.contratos.autentique.client import (
    AutentiqueClientError,
    AutentiqueDocumentSummary,
    fetch_document_summary,
    list_documents,
)
from classificacao_procons.contratos.controle_create_allowlist import (
    BRUNO_DISTRATO_V1_NORMALIZED,
    BRUNO_DISTRATO_V2_NORMALIZED,
)
from classificacao_procons.contratos.controle_dedup import normalize_controle_title
from classificacao_procons.contratos.controle_status import (
    resolve_controle_status_document,
    resolve_signed_at_document,
)
from classificacao_procons.contratos.controle_sync import (
    ControleSyncError,
    _build_track_signature_link,
    _resolve_signer_group_ids,
    reconcile_controle_from_document,
    register_document_in_controle,
)
from classificacao_procons.contratos.controle_tipo import resolve_controle_tipo_label
from classificacao_procons.contratos.controle_track_repair import (
    ensure_controle_dual_tracks_for_document,
)
from classificacao_procons.contratos.monday_contracts import (
    find_controle_items_by_autentique_id,
    load_controle_board_groups,
)
from classificacao_procons.monday.client import MondayClientError, get_api_token_from_env


def _repair_document_tracks(
    *,
    api_token: str,
    document: AutentiqueDocumentSummary,
    build_track_link,
    jan_group_id: str,
    luciano_group_id: str,
    dry_run: bool,
) -> None:
    tipo_label = resolve_controle_tipo_label(
        document_name=document.name,
        min_confidence="low",
    )
    ensure_controle_dual_tracks_for_document(
        api_token=api_token,
        document=document,
        jan_group_id=jan_group_id,
        luciano_group_id=luciano_group_id,
        tipo_label=tipo_label,
        status_label=resolve_controle_status_document(document),
        signed_at=resolve_signed_at_document(document),
        build_track_link=build_track_link,
        dry_run=dry_run,
        allow_create=True,
    )


@dataclass(frozen=True)
class BrunoDistratoPilotResult:
    v2_document_id: str | None
    v2_action: str
    v2_monday_item_id: str | None
    v1_document_ids_reconciled: tuple[str, ...]
    v1_items_updated: int
    dry_run: bool
    detail: str | None = None


def _find_autentique_doc_by_normalized_title(
    documents: list[AutentiqueDocumentSummary],
    *,
    normalized_title: str,
) -> AutentiqueDocumentSummary | None:
    matches = [
        doc
        for doc in documents
        if normalize_controle_title(doc.name) == normalized_title
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    return max(matches, key=lambda d: str(d.created_at or ""))


def run_bruno_distrato_controle_pilot(
    *,
    monday_api_token: str | None = None,
    autentique_api_token: str | None = None,
    v2_document_id: str | None = None,
    max_pages: int = 50,
    dry_run: bool = False,
) -> BrunoDistratoPilotResult:
    """Só o distrato Bruno ``(2)`` (criar) e o distrato v1 nas pendentes (atualizar status)."""
    monday_token = monday_api_token or get_api_token_from_env()
    if not monday_token:
        raise ControleSyncError("MONDAY_API_TOKEN não configurada.")

    try:
        documents = list_documents(api_token=autentique_api_token, max_pages=max_pages)
    except AutentiqueClientError as exc:
        raise ControleSyncError(str(exc)) from exc

    v2_doc: AutentiqueDocumentSummary | None
    if v2_document_id:
        try:
            v2_doc = fetch_document_summary(
                document_id=v2_document_id,
                api_token=autentique_api_token,
            )
        except AutentiqueClientError as exc:
            raise ControleSyncError(str(exc)) from exc
        if normalize_controle_title(v2_doc.name) != BRUNO_DISTRATO_V2_NORMALIZED:
            raise ControleSyncError(
                "document_id informado não é o distrato Bruno (2) esperado pelo piloto.",
            )
    else:
        v2_doc = _find_autentique_doc_by_normalized_title(
            documents,
            normalized_title=BRUNO_DISTRATO_V2_NORMALIZED,
        )

    v2_action = "skipped_no_v2_in_autentique"
    v2_item_id: str | None = None
    groups = load_controle_board_groups(api_token=monday_token)
    jan_group_id, luciano_group_id = _resolve_signer_group_ids(groups)
    if not jan_group_id or not luciano_group_id:
        raise ControleSyncError("Grupos Jan/Luciano não encontrados no Controle.")

    if v2_doc is not None:
        if dry_run:
            linked = find_controle_items_by_autentique_id(
                api_token=monday_token,
                document_id=v2_doc.document_id,
            )
            v2_action = "would_register_v2" if not linked else "would_reconcile_v2"
            v2_item_id = linked[0].item_id if linked else None
            _repair_document_tracks(
                api_token=monday_token,
                document=v2_doc,
                build_track_link=_build_track_signature_link,
                jan_group_id=jan_group_id,
                luciano_group_id=luciano_group_id,
                dry_run=True,
            )
        else:
            reg = register_document_in_controle(
                document_id=v2_doc.document_id,
                document_name=v2_doc.name,
                monday_api_token=monday_token,
                autentique_api_token=autentique_api_token,
            )
            if reg.create_paused:
                v2_action = "create_paused_unexpected"
            elif reg.skipped_duplicate and reg.monday_item_id:
                v2_action = "linked_existing_v2"
                v2_item_id = reg.monday_item_id
            elif reg.skipped_duplicate:
                groups = load_controle_board_groups(api_token=monday_token)
                items = find_controle_items_by_autentique_id(
                    api_token=monday_token,
                    document_id=v2_doc.document_id,
                )
                if items:
                    reconcile_controle_from_document(
                        document=v2_doc,
                        controle_items=items,
                        api_token=monday_token,
                        groups=groups,
                    )
                    v2_action = "reconciled_v2"
                    v2_item_id = items[0].item_id
                else:
                    v2_action = "skipped_duplicate_no_items"
            elif reg.monday_item_id:
                v2_action = "created_v2"
                v2_item_id = reg.monday_item_id
            else:
                v2_action = "register_finished"
        _repair_document_tracks(
            api_token=monday_token,
            document=v2_doc,
            build_track_link=_build_track_signature_link,
            jan_group_id=jan_group_id,
            luciano_group_id=luciano_group_id,
            dry_run=dry_run,
        )

    v1_ids: list[str] = []
    updated = 0
    v1_autentique = _find_autentique_doc_by_normalized_title(
        documents,
        normalized_title=BRUNO_DISTRATO_V1_NORMALIZED,
    )
    if v1_autentique is not None:
        v1_ids.append(v1_autentique.document_id)
        monday_items = find_controle_items_by_autentique_id(
            api_token=monday_token,
            document_id=v1_autentique.document_id,
        )
        if monday_items and not dry_run:
            groups = load_controle_board_groups(api_token=monday_token)
            try:
                result = reconcile_controle_from_document(
                    document=v1_autentique,
                    controle_items=monday_items,
                    api_token=monday_token,
                    groups=groups,
                )
                if result.updated:
                    updated += 1
            except MondayClientError as exc:
                raise ControleSyncError(str(exc)) from exc
            _repair_document_tracks(
                api_token=monday_token,
                document=v1_autentique,
                build_track_link=_build_track_signature_link,
                jan_group_id=jan_group_id,
                luciano_group_id=luciano_group_id,
                dry_run=dry_run,
            )
        elif monday_items and dry_run:
            updated = len(monday_items)

    return BrunoDistratoPilotResult(
        v2_document_id=v2_doc.document_id if v2_doc else None,
        v2_action=v2_action,
        v2_monday_item_id=v2_item_id,
        v1_document_ids_reconciled=tuple(v1_ids),
        v1_items_updated=updated,
        dry_run=dry_run,
        detail="Somente distrato Bruno v1/v2; demais documentos ignorados.",
    )
