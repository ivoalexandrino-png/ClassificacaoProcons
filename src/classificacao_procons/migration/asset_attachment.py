"""Sunday link attachment idempotente para item.assets materializados."""

from __future__ import annotations

from classificacao_procons.migration.asset_models import (
    MigrationAssetError,
    MondayAssetMetadata,
    StorageObjectRecord,
    SundayAttachmentPlan,
)
from classificacao_procons.migration.asset_storage import validate_stable_drive_public_url
from classificacao_procons.sunday.models import Attachment


def asset_attachment_marker(*, board_id: str, item_id: str, asset_id: str) -> str:
    return f"[monday-asset:{board_id}:{item_id}:{asset_id}]"


def asset_attachment_filename(
    *,
    board_id: str,
    item_id: str,
    asset_id: str,
    original_filename: str,
) -> str:
    marker = asset_attachment_marker(
        board_id=board_id,
        item_id=item_id,
        asset_id=asset_id,
    )
    return f"{marker} {original_filename}"


def find_attachment_by_marker(
    attachments: list[Attachment],
    marker: str,
) -> Attachment | None:
    matches = [
        attachment
        for attachment in attachments
        if attachment.filename and marker in attachment.filename
    ]
    if len(matches) > 1:
        raise MigrationAssetError(
            f"AMBIGUOUS: múltiplos attachments com marker {marker}.",
        )
    return matches[0] if matches else None


def plan_sunday_attachment(
    *,
    asset: MondayAssetMetadata,
    storage: StorageObjectRecord,
) -> SundayAttachmentPlan:
    marker = asset_attachment_marker(
        board_id=asset.board_id,
        item_id=asset.item_id,
        asset_id=asset.asset_id,
    )
    filename = asset_attachment_filename(
        board_id=asset.board_id,
        item_id=asset.item_id,
        asset_id=asset.asset_id,
        original_filename=storage.original_filename,
    )
    if not storage.public_url.startswith("http"):
        raise MigrationAssetError("Storage URL inválida para Sunday attachment.")
    validate_stable_drive_public_url(storage.public_url, file_id=storage.drive_file_id)
    return SundayAttachmentPlan(
        board_id=asset.board_id,
        item_id=asset.item_id,
        asset_id=asset.asset_id,
        storage_url=storage.public_url,
        attachment_filename=filename,
        marker=marker,
    )


def ensure_sunday_link_attachment(
    client,
    *,
    sunday_item_id: str,
    plan: SundayAttachmentPlan,
    existing_attachments: list[Attachment] | None = None,
) -> tuple[Attachment, bool]:
    """Retorna (attachment, created). created=False se idempotente."""
    attachments = existing_attachments
    if attachments is None:
        attachments = client.list_attachments(sunday_item_id)
    existing = find_attachment_by_marker(attachments, plan.marker)
    if existing is not None:
        return existing, False
    created = client.add_link_attachment(
        sunday_item_id,
        plan.storage_url,
        filename=plan.attachment_filename,
    )
    return created, True
