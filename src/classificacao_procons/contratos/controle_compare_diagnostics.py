"""Diagnóstico read-only Autentique → Controle (expected tracks, escopo, ações propostas)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from classificacao_procons.contratos.autentique.client import AutentiqueDocumentSummary
from classificacao_procons.contratos.controle_autentique_plan import (
    ControlePlanAction,
    classify_autentique_document_for_controle,
)
from classificacao_procons.contratos.controle_dedup import find_exact_title_matches
from classificacao_procons.contratos.controle_link_suggestions import _item_has_autentique_link
from classificacao_procons.contratos.controle_required_tracks import (
    detect_internal_signers,
    resolve_expected_tracks,
)
from classificacao_procons.contratos.controle_scope import (
    ControleScopeClassification,
    classify_controle_scope,
)
from classificacao_procons.contratos.controle_status import resolve_controle_status_for_track
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import (
    ControleAssinaturasIndex,
    infer_controle_signer_track,
)


class ControleProposedAction(StrEnum):
    NONE = "none"
    LINK_EXISTING = "link_existing"
    RECONCILE_STATUS = "reconcile_status"
    MISSING_TRACK = "missing_track"
    UNEXPECTED_TRACK = "unexpected_track"
    DUPLICATE = "duplicate"
    IGNORED_NON_CONTRACT = "ignored_non_contract"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True)
class ControleSignerSummary:
    public_id: str
    name: str | None
    email: str | None
    signed_at: str | None


@dataclass(frozen=True)
class ControleDocumentDiagnosticRow:
    autentique_document_id: str
    document_name: str
    document_status: str
    signers: tuple[ControleSignerSummary, ...]
    internal_signers_detected: tuple[str, ...]
    expected_tracks: frozenset[str]
    existing_tracks: frozenset[str]
    missing_tracks: frozenset[str]
    unexpected_tracks: frozenset[str]
    status_expected_by_track: dict[str, str]
    status_current_by_track: dict[str, str | None]
    scope_classification: str
    scope_reason: str
    duplicate_items: tuple[tuple[str, str], ...]
    legacy_items_without_autentique_id: tuple[tuple[str, str], ...]
    proposed_action: str


@dataclass(frozen=True)
class ControleCompareDiagnosticSummary:
    documents_analyzed: int
    expected_tracks_jan_only: int
    expected_tracks_luciano_only: int
    expected_tracks_both: int
    expected_tracks_none: int
    scope_eligible: int
    scope_ineligible: int
    scope_manual_review: int
    proposed_action_counts: dict[str, int]
    missing_track_total: int
    unexpected_track_total: int
    status_divergence_total: int


def _serialize_signers(document: AutentiqueDocumentSummary) -> tuple[ControleSignerSummary, ...]:
    return tuple(
        ControleSignerSummary(
            public_id=signer.public_id,
            name=signer.name,
            email=signer.email,
            signed_at=signer.signed_at,
        )
        for signer in document.signatures
    )


def _document_status_label(document: AutentiqueDocumentSummary) -> str:
    if document.is_fully_signed:
        return "fully_signed"
    if document.signed_pdf_url:
        return "signed_pdf_present"
    if any(signer.signed_at for signer in document.signatures):
        return "partially_signed"
    return "pending"


def _existing_tracks_for_document(
    *,
    document_id: str,
    index: ControleAssinaturasIndex,
) -> dict[str, list[ControleAssinaturasItem]]:
    items = index.items_for_document_id(document_id)
    by_track: dict[str, list[ControleAssinaturasItem]] = {"jan": [], "luciano": []}
    for item in items:
        track = infer_controle_signer_track(item)
        if track in by_track:
            by_track[track].append(item)
        else:
            by_track.setdefault("unknown", []).append(item)
    return by_track


def _tracks_set(by_track: dict[str, list[ControleAssinaturasItem]]) -> frozenset[str]:
    return frozenset(
        track for track, group in by_track.items() if track in ("jan", "luciano") and group
    )


def _status_diverges(
    *,
    expected: dict[str, str],
    current: dict[str, str | None],
) -> bool:
    for track, want in expected.items():
        have = current.get(track)
        if have is None:
            continue
        if (have or "").casefold().strip() != want.casefold().strip():
            return True
    return False


def diagnose_controle_document(
    *,
    document: AutentiqueDocumentSummary,
    index: ControleAssinaturasIndex,
) -> ControleDocumentDiagnosticRow:
    detected = detect_internal_signers(document)
    internal_labels: list[str] = []
    if detected.jan:
        internal_labels.append("jan")
    if detected.luciano:
        internal_labels.append("luciano")

    expected = resolve_expected_tracks(document)
    scope, scope_reason = classify_controle_scope(document, expected_tracks=expected)

    by_track = _existing_tracks_for_document(document_id=document.document_id, index=index)
    existing = _tracks_set(by_track)
    missing = frozenset(track for track in expected if track not in existing)
    unexpected = frozenset(track for track in existing if track not in expected)

    status_expected = {
        track: resolve_controle_status_for_track(document, track=track)
        for track in expected | existing
    }
    status_current: dict[str, str | None] = {}
    for track in ("jan", "luciano"):
        group = by_track.get(track) or []
        if not group:
            continue
        status_current[track] = group[0].status

    duplicate_items: list[tuple[str, str]] = []
    for track, group in by_track.items():
        if track not in ("jan", "luciano") or len(group) < 2:
            continue
        for item in group[1:]:
            duplicate_items.append((item.item_id, item.name))

    legacy_without_id: list[tuple[str, str]] = []
    for item in find_exact_title_matches(document_name=document.name, items=index.all_items):
        if _item_has_autentique_link(item, index):
            continue
        legacy_without_id.append((item.item_id, item.name))

    proposed = ControleProposedAction.NONE
    if scope == ControleScopeClassification.INELIGIBLE:
        proposed = ControleProposedAction.IGNORED_NON_CONTRACT
    elif scope == ControleScopeClassification.MANUAL_REVIEW:
        proposed = ControleProposedAction.MANUAL_REVIEW
    elif duplicate_items:
        proposed = ControleProposedAction.DUPLICATE
    elif unexpected:
        proposed = ControleProposedAction.UNEXPECTED_TRACK
    elif missing:
        proposed = ControleProposedAction.MISSING_TRACK
    elif legacy_without_id and not existing:
        plan = classify_autentique_document_for_controle(document=document, index=index)
        if plan.action == ControlePlanAction.VINCULAR:
            proposed = ControleProposedAction.LINK_EXISTING
        elif plan.action == ControlePlanAction.ATUALIZAR:
            proposed = ControleProposedAction.RECONCILE_STATUS
    elif existing and _status_diverges(expected=status_expected, current=status_current):
        proposed = ControleProposedAction.RECONCILE_STATUS
    elif not expected and not existing:
        proposed = ControleProposedAction.NONE

    return ControleDocumentDiagnosticRow(
        autentique_document_id=document.document_id,
        document_name=document.name,
        document_status=_document_status_label(document),
        signers=_serialize_signers(document),
        internal_signers_detected=tuple(internal_labels),
        expected_tracks=expected,
        existing_tracks=existing,
        missing_tracks=missing,
        unexpected_tracks=unexpected,
        status_expected_by_track=status_expected,
        status_current_by_track=status_current,
        scope_classification=scope.value,
        scope_reason=scope_reason,
        duplicate_items=tuple(duplicate_items),
        legacy_items_without_autentique_id=tuple(legacy_without_id),
        proposed_action=proposed.value,
    )


def build_controle_compare_diagnostics(
    *,
    documents: tuple[AutentiqueDocumentSummary, ...] | list[AutentiqueDocumentSummary],
    index: ControleAssinaturasIndex,
) -> tuple[ControleDocumentDiagnosticRow, ...]:
    return tuple(
        diagnose_controle_document(document=document, index=index) for document in documents
    )


def summarize_controle_compare_diagnostics(
    rows: tuple[ControleDocumentDiagnosticRow, ...],
) -> ControleCompareDiagnosticSummary:
    jan_only = luciano_only = both = none_tracks = 0
    scope_eligible = scope_ineligible = scope_manual = 0
    action_counts: dict[str, int] = {}
    missing_total = unexpected_total = status_div = 0

    for row in rows:
        exp = row.expected_tracks
        if exp == frozenset({"jan"}):
            jan_only += 1
        elif exp == frozenset({"luciano"}):
            luciano_only += 1
        elif exp == frozenset({"jan", "luciano"}):
            both += 1
        elif not exp:
            none_tracks += 1

        if row.scope_classification == ControleScopeClassification.ELIGIBLE.value:
            scope_eligible += 1
        elif row.scope_classification == ControleScopeClassification.INELIGIBLE.value:
            scope_ineligible += 1
        else:
            scope_manual += 1

        action_counts[row.proposed_action] = action_counts.get(row.proposed_action, 0) + 1
        missing_total += len(row.missing_tracks)
        unexpected_total += len(row.unexpected_tracks)
        if _status_diverges(
            expected=row.status_expected_by_track,
            current=row.status_current_by_track,
        ):
            status_div += 1

    return ControleCompareDiagnosticSummary(
        documents_analyzed=len(rows),
        expected_tracks_jan_only=jan_only,
        expected_tracks_luciano_only=luciano_only,
        expected_tracks_both=both,
        expected_tracks_none=none_tracks,
        scope_eligible=scope_eligible,
        scope_ineligible=scope_ineligible,
        scope_manual_review=scope_manual,
        proposed_action_counts=action_counts,
        missing_track_total=missing_total,
        unexpected_track_total=unexpected_total,
        status_divergence_total=status_div,
    )


def diagnostic_row_to_dict(row: ControleDocumentDiagnosticRow) -> dict[str, object]:
    return {
        "autentique_document_id": row.autentique_document_id,
        "document_name": row.document_name,
        "document_status": row.document_status,
        "signers": [
            {
                "public_id": s.public_id,
                "name": s.name,
                "email": s.email,
                "signed_at": s.signed_at,
            }
            for s in row.signers
        ],
        "internal_signers_detected": list(row.internal_signers_detected),
        "expected_tracks": sorted(row.expected_tracks),
        "existing_tracks": sorted(row.existing_tracks),
        "missing_tracks": sorted(row.missing_tracks),
        "unexpected_tracks": sorted(row.unexpected_tracks),
        "status_expected_by_track": dict(row.status_expected_by_track),
        "status_current_by_track": dict(row.status_current_by_track),
        "scope_classification": row.scope_classification,
        "scope_reason": row.scope_reason,
        "duplicate_items": [
            {"item_id": item_id, "name": name} for item_id, name in row.duplicate_items
        ],
        "legacy_items_without_autentique_id": [
            {"item_id": item_id, "name": name}
            for item_id, name in row.legacy_items_without_autentique_id
        ],
        "proposed_action": row.proposed_action,
    }
