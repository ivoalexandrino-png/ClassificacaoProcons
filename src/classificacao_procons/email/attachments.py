"""Anexos genéricos em mensagens Gmail."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GmailAttachmentRef:
    filename: str
    attachment_id: str
    mime_type: str
    size: int


def list_message_attachments(payload: dict[str, Any]) -> tuple[GmailAttachmentRef, ...]:
    """Lista partes MIME com filename e attachmentId."""
    found: list[GmailAttachmentRef] = []

    def walk(part: dict[str, Any]) -> None:
        filename = (part.get("filename") or "").strip()
        body = part.get("body", {})
        attachment_id = body.get("attachmentId")
        if filename and attachment_id:
            found.append(
                GmailAttachmentRef(
                    filename=filename,
                    attachment_id=str(attachment_id),
                    mime_type=part.get("mimeType", ""),
                    size=int(body.get("size", 0)),
                ),
            )
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    return tuple(found)


def download_gmail_attachment(
    service: Any,
    *,
    message_id: str,
    attachment: GmailAttachmentRef,
    destination: Path,
) -> Path:
    """Baixa um anexo para o caminho indicado."""
    response = (
        service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message_id, id=attachment.attachment_id)
        .execute()
    )
    data = response.get("data", "")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(base64.urlsafe_b64decode(data.encode("utf-8")))
    return destination
