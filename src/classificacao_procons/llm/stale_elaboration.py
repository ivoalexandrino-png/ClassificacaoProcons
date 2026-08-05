"""Seleção de respostas automáticas geradas antes do alinhamento SAC (#122)."""

from __future__ import annotations

from datetime import UTC, datetime

from classificacao_procons.drive.client import DriveClientError
from classificacao_procons.drive.reader import (
    newest_automatic_response_generated_at,
    resolve_sac_folder_context,
)
from classificacao_procons.models import MondayCaseReady
from classificacao_procons.monday.cases import list_cases_with_elaborated_responses

# Merge do alinhamento SAC (#122) em main; re-elaboração da Nathalia ~19:55 UTC no mesmo dia.
DEFAULT_PRE_SAC_ALIGNMENT_CUTOFF = datetime(2026, 8, 5, 19, 54, tzinfo=UTC)


def parse_utc_cutoff(value: str) -> datetime:
    """Interpreta instante ISO-8601 (aceita ``Z`` ou offset)."""
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def is_automatic_response_older_than(
    *,
    docs_sac_url: str,
    before: datetime,
    token_path: str,
) -> bool:
    """True se a resposta automática mais recente no Drive é anterior a ``before``."""
    cutoff = before.astimezone(UTC)
    try:
        sac_context = resolve_sac_folder_context(
            docs_sac_url=docs_sac_url,
            token_path=token_path,
        )
    except DriveClientError:
        return False

    generated_at = newest_automatic_response_generated_at(
        consumer_folder_id=sac_context.consumer_folder_id,
        token_path=token_path,
    )
    if generated_at is None:
        return False
    return generated_at.astimezone(UTC) < cutoff


def list_cases_with_stale_automatic_responses(
    *,
    before: datetime,
    api_token: str,
    token_path: str,
    max_cases: int,
) -> list[MondayCaseReady]:
    """Casos com resposta no Monday cuja geração no Drive é anterior ao corte SAC."""
    if max_cases < 1:
        return []

    candidates = list_cases_with_elaborated_responses(api_token=api_token, limit=None)
    stale: list[MondayCaseReady] = []
    for case in candidates:
        if len(stale) >= max_cases:
            break
        if is_automatic_response_older_than(
            docs_sac_url=case.docs_sac_url,
            before=before,
            token_path=token_path,
        ):
            stale.append(case)
    return stale
