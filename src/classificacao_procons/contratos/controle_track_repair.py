"""Garante par Jan/Luciano e metadados no Controle Assinaturas.

Sync automático: workflows `contratos-sync-controle.yml` e `contratos-sync-after-agent-merge.yml`
(via `agent-pr-automerge`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from classificacao_procons.contratos.autentique.client import AutentiqueDocumentSummary
from classificacao_procons.contratos.constants import (
    CONTROLE_LINK_TRACK_JAN,
    CONTROLE_LINK_TRACK_LUCIANO,
    CONTROLE_QUEM_ASSINA_JAN,
    CONTROLE_QUEM_ASSINA_LUCIANO,
)
from classificacao_procons.contratos.controle_required_tracks import (
    document_required_controle_tracks,
)
from classificacao_procons.contratos.controle_status import (
    resolve_controle_status_for_track,
    resolve_signed_at_for_track,
)
from classificacao_procons.contratos.models import ControleAssinaturasItem
from classificacao_procons.contratos.monday_contracts import (
    archive_controle_item,
    create_controle_assinatura_item,
    find_controle_items_by_autentique_id,
    infer_controle_signer_track,
    pick_canonical_controle_item,
    update_controle_item_fields,
)

CONTROLE_SIGNER_LABEL_JAN = CONTROLE_QUEM_ASSINA_JAN
CONTROLE_SIGNER_LABEL_LUCIANO = CONTROLE_QUEM_ASSINA_LUCIANO
CONTROLE_PLATFORM_AUTENTIQUE = "Autentique"


@dataclass(frozen=True)
class ControleTrackRepairResult:
    document_id: str
    created_jan: bool
    created_luciano: bool
    updated_items: int
    archived_duplicates: int
    duplicate_tracks_remaining: int


def classify_controle_item_track(
    item: ControleAssinaturasItem,
    *,
    jan_group_id: str | None,
    luciano_group_id: str | None,
) -> str:
    """Classifica item como ``jan`` ou ``luciano`` (nunca ``unknown`` para reparo)."""
    inferred = infer_controle_signer_track(item)
    if inferred in ("jan", "luciano"):
        return inferred
    if item.tipo and str(item.tipo).strip():
        return "jan"
    if luciano_group_id and item.group_id == luciano_group_id:
        return "luciano"
    if jan_group_id and item.group_id == jan_group_id:
        return "jan"
    return "luciano"


def controle_dual_tracks_satisfied_for_items(
    document: AutentiqueDocumentSummary,
    items: tuple[ControleAssinaturasItem, ...] | list[ControleAssinaturasItem],
) -> bool:
    """True quando cada fila exigida pelo Autentique já tem item no Monday."""
    required = document_required_controle_tracks(document)
    if not required:
        return True
    present = {infer_controle_signer_track(item) for item in items}
    return all(track in present for track in required)


def parse_autentique_created_date(document: AutentiqueDocumentSummary) -> date | None:
    raw = document.created_at
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def _group_items_by_track(
    items: tuple[ControleAssinaturasItem, ...],
    *,
    jan_group_id: str,
    luciano_group_id: str,
) -> dict[str, list[ControleAssinaturasItem]]:
    by_track: dict[str, list[ControleAssinaturasItem]] = {"jan": [], "luciano": []}
    for item in items:
        track = classify_controle_item_track(
            item,
            jan_group_id=jan_group_id,
            luciano_group_id=luciano_group_id,
        )
        by_track[track].append(item)
    return by_track


def ensure_controle_dual_tracks_for_document(
    *,
    api_token: str,
    document: AutentiqueDocumentSummary,
    jan_group_id: str,
    luciano_group_id: str,
    tipo_label: str | None,
    status_label: str,
    signed_at: date | None,
    build_track_link,
    dry_run: bool = False,
    allow_create: bool = True,
) -> ControleTrackRepairResult:
    """Cria fila faltante, corrige grupo/colunas e marca ``controle_track`` nos links."""
    inclusion_date = parse_autentique_created_date(document)
    short_link = document.primary_signature_link()

    items = find_controle_items_by_autentique_id(
        api_token=api_token,
        document_id=document.document_id,
    )
    by_track = _group_items_by_track(
        items,
        jan_group_id=jan_group_id,
        luciano_group_id=luciano_group_id,
    )

    required_tracks = document_required_controle_tracks(document)

    created_jan = False
    created_luciano = False
    archived = 0

    for track in ("jan", "luciano"):
        if track in required_tracks:
            continue
        for stray in by_track[track]:
            if dry_run:
                archived += 1
            else:
                archive_controle_item(api_token=api_token, item_id=stray.item_id)
                archived += 1
        by_track[track] = []

    if "jan" in required_tracks and not by_track["jan"]:
        if not allow_create:
            pass
        elif dry_run:
            created_jan = True
        else:
            create_controle_assinatura_item(
                api_token=api_token,
                item_name=document.name,
                group_id=jan_group_id,
                signature_link_text=build_track_link(
                    document=document,
                    track="jan",
                    short_link=short_link,
                ),
                status_label=resolve_controle_status_for_track(document, track="jan"),
                tipo_label=tipo_label,
                signed_at=resolve_signed_at_for_track(document, track="jan"),
                signer_label=CONTROLE_SIGNER_LABEL_JAN,
                platform_name=CONTROLE_PLATFORM_AUTENTIQUE,
                inclusion_date=inclusion_date,
            )
            created_jan = True

    if "luciano" in required_tracks and not by_track["luciano"]:
        if not allow_create:
            pass
        elif dry_run:
            created_luciano = True
        else:
            create_controle_assinatura_item(
                api_token=api_token,
                item_name=document.name,
                group_id=luciano_group_id,
                signature_link_text=build_track_link(
                    document=document,
                    track="luciano",
                    short_link=short_link,
                ),
                status_label=resolve_controle_status_for_track(document, track="luciano"),
                tipo_label=None,
                signed_at=resolve_signed_at_for_track(document, track="luciano"),
                signer_label=CONTROLE_SIGNER_LABEL_LUCIANO,
                platform_name=CONTROLE_PLATFORM_AUTENTIQUE,
                inclusion_date=inclusion_date,
            )
            created_luciano = True

    if not dry_run and (created_jan or created_luciano):
        items = find_controle_items_by_autentique_id(
            api_token=api_token,
            document_id=document.document_id,
        )
        by_track = _group_items_by_track(
            items,
            jan_group_id=jan_group_id,
            luciano_group_id=luciano_group_id,
        )

    updated = 0
    duplicates = 0
    for track, track_items in by_track.items():
        if track not in required_tracks:
            continue
        if len(track_items) > 1:
            duplicates += len(track_items) - 1
            canonical_pick = pick_canonical_controle_item(tuple(track_items)) or track_items[0]
            for extra in track_items:
                if extra.item_id == canonical_pick.item_id:
                    continue
                if dry_run:
                    archived += 1
                else:
                    archive_controle_item(api_token=api_token, item_id=extra.item_id)
                    archived += 1
            track_items = [canonical_pick]

        canonical = track_items[0] if track_items else None
        if canonical is None:
            continue

        target_group = jan_group_id if track == "jan" else luciano_group_id
        target_tipo = tipo_label if track == "jan" else None
        clear_tipo = (
            track == "jan"
            and tipo_label is None
            and bool(canonical.tipo and str(canonical.tipo).strip())
        )
        target_signer = (
            CONTROLE_SIGNER_LABEL_JAN if track == "jan" else CONTROLE_SIGNER_LABEL_LUCIANO
        )
        marker = CONTROLE_LINK_TRACK_JAN if track == "jan" else CONTROLE_LINK_TRACK_LUCIANO
        link = canonical.signature_link or ""
        needs_marker = marker.casefold() not in link.casefold()
        needs_group = canonical.group_id != target_group

        track_status = resolve_controle_status_for_track(document, track=track)
        track_signed_at = resolve_signed_at_for_track(document, track=track)

        if not needs_marker and not needs_group:
            if dry_run:
                updated += 1
            else:
                update_controle_item_fields(
                    api_token=api_token,
                    item_id=canonical.item_id,
                    status_label=track_status,
                    signed_at=track_signed_at,
                    tipo_label=target_tipo,
                    clear_tipo=clear_tipo,
                    signer_label=target_signer,
                    platform_name=CONTROLE_PLATFORM_AUTENTIQUE,
                    inclusion_date=inclusion_date,
                )
                updated += 1
            continue

        if dry_run:
            updated += 1
            continue

        new_link = (
            build_track_link(document=document, track=track, short_link=short_link)
            if needs_marker
            else None
        )
        update_controle_item_fields(
            api_token=api_token,
            item_id=canonical.item_id,
            group_id=target_group if needs_group else None,
            current_group_id=canonical.group_id,
            status_label=track_status,
            signed_at=track_signed_at,
            tipo_label=target_tipo,
            clear_tipo=clear_tipo,
            signer_label=target_signer,
            platform_name=CONTROLE_PLATFORM_AUTENTIQUE,
            inclusion_date=inclusion_date,
            signature_link_text=new_link,
        )
        updated += 1

    return ControleTrackRepairResult(
        document_id=document.document_id,
        created_jan=created_jan,
        created_luciano=created_luciano,
        updated_items=updated,
        archived_duplicates=archived,
        duplicate_tracks_remaining=max(0, duplicates - archived),
    )
