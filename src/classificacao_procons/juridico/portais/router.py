"""Roteia a consulta de teor para o portal certo, pelo sistema do DataJud.

Um mesmo tribunal usa vários sistemas (e-SAJ, PJe, Projudi, eproc). O número
CNJ não diz qual; o DataJud sim (campo ``sistema``). Este módulo escolhe o
cliente adequado e devolve o teor, ou um erro tratável quando o sistema não é
suportado (aí o fluxo segue no DataJud).
"""

from __future__ import annotations

from classificacao_procons.juridico.acessos import get_tribunal_credential
from classificacao_procons.juridico.cnj import datajud_alias, tribunal_acronym
from classificacao_procons.juridico.portais import esaj, pje, projudi
from classificacao_procons.juridico.portais.base import (
    PortalError,
    PortalRequiresInteraction,
    PortalUnsupported,
    ProcessContent,
)


def _normalize_system(sistema: str | None) -> str:
    return (sistema or "").strip().upper()


def fetch_process_content(
    process_number: str,
    *,
    sistema: str | None,
    tribunal: str | None = None,
    headless: bool = True,
    api_token: str | None = None,
) -> ProcessContent:
    """Consulta o teor no portal correspondente ao ``sistema`` do processo."""
    acronym = tribunal or tribunal_acronym(process_number)
    system = _normalize_system(sistema)

    if "SAJ" in system or (not system and acronym and acronym.startswith("TJ")):
        # e-SAJ: consulta pública primeiro; segredo cai no autenticado no CLI.
        return esaj.fetch_process_content_public(process_number, headless=headless)

    if "PROJUDI" in system:
        if acronym is None:
            raise PortalError("Tribunal não identificado para o Projudi.")
        credential = get_tribunal_credential(acronym, api_token=api_token)
        if credential is None:
            raise PortalUnsupported(
                f"Projudi de {acronym} sem credencial no quadro Acessos; "
                "andamentos seguem pelo DataJud.",
            )
        return projudi.fetch_process_content(
            process_number,
            tribunal_acronym=acronym,
            credential=credential,
            headless=headless,
        )

    if "PJE" in system:
        alias = datajud_alias(process_number) or ""
        return pje.fetch_process_content_public(
            process_number,
            alias=alias,
            headless=headless,
        )

    raise PortalUnsupported(
        f"Sistema '{sistema}' ainda sem scraper; andamentos seguem pelo DataJud.",
    )


__all__ = [
    "PortalError",
    "PortalRequiresInteraction",
    "PortalUnsupported",
    "ProcessContent",
    "fetch_process_content",
]
