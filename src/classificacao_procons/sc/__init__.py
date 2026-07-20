"""Integração com Procon Santa Catarina (processos SSP)."""

from classificacao_procons.sc.attachments import (
    ScAttachmentError,
    download_ssp_pdf_attachment,
    find_ssp_pdf_attachment,
)
from classificacao_procons.sc.deadlines import (
    SC_PROCON_RESPONSE_BUSINESS_DAYS,
    calculate_sc_deadlines,
)
from classificacao_procons.sc.email_parser import (
    SC_ORIGINAL_SENDER,
    SC_STATE_LABEL,
    ScEmailParseError,
    extract_ssp_protocol_number,
    is_sc_ssp_notification,
    parse_sc_ssp_notification,
)
from classificacao_procons.sc.pdf_parser import (
    ScPdfParseError,
    parse_sc_ssp_pdf,
)

__all__ = [
    "SC_ORIGINAL_SENDER",
    "SC_PROCON_RESPONSE_BUSINESS_DAYS",
    "SC_STATE_LABEL",
    "ScAttachmentError",
    "ScEmailParseError",
    "ScPdfParseError",
    "calculate_sc_deadlines",
    "download_ssp_pdf_attachment",
    "extract_ssp_protocol_number",
    "find_ssp_pdf_attachment",
    "is_sc_ssp_notification",
    "parse_sc_ssp_notification",
    "parse_sc_ssp_pdf",
]
