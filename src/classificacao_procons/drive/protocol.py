"""Validação de protocolo entre Monday e arquivos do Drive."""

from __future__ import annotations

import re

from classificacao_procons.drive.errors import DriveClientError

PROTOCOL_MISMATCH_PREFIX = "Pasta Docs SAC inconsistente:"
_DATE_SUFFIX_PATTERN = re.compile(r"^\d{2}-\d{2}-\d{4}$")


def normalize_protocol_number(protocol: str) -> str:
    """Normaliza protocolo para comparação (ex.: 1759897/2026 → 1759897-2026)."""
    return protocol.strip().replace("/", "-").casefold()


def extract_protocol_from_procon_pdf_name(name: str) -> str | None:
    """Extrai protocolo do nome padrão de PDF Procon/PA no Drive."""
    if not name.casefold().endswith(".pdf"):
        return None

    parts = [segment.strip() for segment in name[:-4].split(" - ")]
    if len(parts) < 4:
        return None

    date_part = parts[-1]
    if date_part != "sem-data" and not _DATE_SUFFIX_PATTERN.fullmatch(date_part):
        return None

    protocol = parts[-2].strip()
    return protocol or None


def protocols_match(expected: str, found: str) -> bool:
    """Compara protocolos tolerando barra vs hífen."""
    return normalize_protocol_number(expected) == normalize_protocol_number(found)


def build_disambiguated_folder_name(*, consumer_name: str, protocol_number: str) -> str:
    """Monta nome de pasta quando há homônimos (ex.: NOME - 1759897-2026)."""
    cleaned_name = " ".join(consumer_name.split()).strip()
    cleaned_protocol = " ".join(protocol_number.split()).strip().replace("/", "-")
    if not cleaned_name:
        raise DriveClientError("Nome da consumidora vazio.")
    if not cleaned_protocol:
        raise DriveClientError("Número de protocolo vazio.")
    return f"{cleaned_name} - {cleaned_protocol}"[:200]


def build_protocol_mismatch_error(
    *,
    expected_protocol: str,
    found_protocol: str | None,
    pdf_name: str,
) -> str:
    found_label = found_protocol or "desconhecido"
    return (
        f"{PROTOCOL_MISMATCH_PREFIX} Monday protocolo {expected_protocol}, "
        f"PDF na pasta indica {found_label} ({pdf_name}). "
        "Atualize a coluna Docs SAC para a pasta correta."
    )


def is_protocol_mismatch_error(message: str) -> bool:
    return message.startswith(PROTOCOL_MISMATCH_PREFIX)


def validate_complaint_pdf_protocol(
    *,
    pdf_name: str,
    expected_protocol: str | None,
) -> None:
    """Falha cedo se o PDF da pasta não corresponde ao protocolo esperado."""
    if not expected_protocol:
        return

    found_protocol = extract_protocol_from_procon_pdf_name(pdf_name)
    if found_protocol is None:
        raise DriveClientError(
            build_protocol_mismatch_error(
                expected_protocol=expected_protocol,
                found_protocol=None,
                pdf_name=pdf_name,
            ),
        )

    if not protocols_match(expected_protocol, found_protocol):
        raise DriveClientError(
            build_protocol_mismatch_error(
                expected_protocol=expected_protocol,
                found_protocol=found_protocol,
                pdf_name=pdf_name,
            ),
        )
