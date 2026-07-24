"""Download de anexos PDF de e-mails ALERJ via Gmail API."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ALERJ_PDF_NAME_PATTERN = re.compile(r"not\.pdf$", re.IGNORECASE)


class AlerjAttachmentError(RuntimeError):
    """Erro ao localizar ou baixar PDF ALERJ do e-mail."""


@dataclass(frozen=True)
class AlerjPdfAttachment:
    filename: str
    attachment_id: str
    size: int


def _decode_body_data(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def _is_alerj_pdf(filename: str) -> bool:
    if not filename.lower().endswith(".pdf"):
        return False
    return _ALERJ_PDF_NAME_PATTERN.search(filename) is not None


def find_alerj_pdf_attachment(payload: dict[str, Any]) -> AlerjPdfAttachment | None:
    """Localiza o PDF da notificação ALERJ no payload MIME do Gmail."""
    matches: list[AlerjPdfAttachment] = []

    def walk(part: dict[str, Any]) -> None:
        filename = part.get("filename", "")
        body = part.get("body", {})
        attachment_id = body.get("attachmentId")
        if filename and attachment_id and _is_alerj_pdf(filename):
            matches.append(
                AlerjPdfAttachment(
                    filename=filename,
                    attachment_id=attachment_id,
                    size=int(body.get("size", 0)),
                ),
            )
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    if not matches:
        return None
    return max(matches, key=lambda item: item.size)


def download_alerj_pdf_attachment(
    service: Any,
    *,
    message_id: str,
    payload: dict[str, Any],
    download_dir: Path,
    protocol_number: str,
) -> Path:
    """Baixa o PDF ALERJ para o diretório local e retorna o caminho."""
    attachment = find_alerj_pdf_attachment(payload)
    if attachment is None:
        raise AlerjAttachmentError("PDF da notificação ALERJ não encontrado no e-mail.")

    try:
        response = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment.attachment_id)
            .execute()
        )
    except Exception as exc:
        raise AlerjAttachmentError("Falha ao baixar anexo PDF do e-mail ALERJ.") from exc

    data = _decode_body_data(response["data"])
    download_dir.mkdir(parents=True, exist_ok=True)
    safe_protocol = protocol_number.replace("/", "-")
    target_path = download_dir / f"alerj-{safe_protocol}.pdf"
    target_path.write_bytes(data)
    return target_path
