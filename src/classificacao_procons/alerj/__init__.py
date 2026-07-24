"""Integração com ALERJ (Comissão de Defesa do Consumidor do RJ)."""

from classificacao_procons.alerj.attachments import (
    AlerjAttachmentError,
    download_alerj_pdf_attachment,
    find_alerj_pdf_attachment,
)
from classificacao_procons.alerj.deadlines import (
    ALERJ_PROCON_RESPONSE_DAYS,
    calculate_alerj_deadlines,
)
from classificacao_procons.alerj.email_parser import (
    ALERJ_ORIGINAL_SENDER,
    ALERJ_STATE_LABEL,
    AlerjEmailParseError,
    extract_alerj_protocol_number,
    is_alerj_notification,
    parse_alerj_notification,
)
from classificacao_procons.alerj.pdf_parser import (
    AlerjPdfParseError,
    parse_alerj_pdf,
)

__all__ = [
    "ALERJ_ORIGINAL_SENDER",
    "ALERJ_PROCON_RESPONSE_DAYS",
    "ALERJ_STATE_LABEL",
    "AlerjAttachmentError",
    "AlerjEmailParseError",
    "AlerjPdfParseError",
    "calculate_alerj_deadlines",
    "download_alerj_pdf_attachment",
    "extract_alerj_protocol_number",
    "find_alerj_pdf_attachment",
    "is_alerj_notification",
    "parse_alerj_notification",
    "parse_alerj_pdf",
]
