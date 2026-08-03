"""Política de criação de novos itens no Monday Controle Assinaturas."""

from __future__ import annotations

import os

ENV_PAUSE_CREATE = "CONTROLE_PAUSE_CREATE"
_PAUSED_VALUES = frozenset({"1", "true", "yes", "on"})


def is_controle_create_paused(*, allow_create: bool | None = None) -> bool:
    """Retorna True quando novos itens no Controle não devem ser criados.

    Por padrão a criação fica **pausada** (``CONTROLE_PAUSE_CREATE`` default ``true``).
    Passe ``allow_create=True`` (CLI ``--allow-create``) para forçar criação numa execução.
  """
    if allow_create is True:
        return False
    if allow_create is False:
        return True
    raw = os.environ.get(ENV_PAUSE_CREATE, "true").strip().casefold()
    return raw in _PAUSED_VALUES


def controle_create_paused_message() -> str:
    return (
        "Criação de itens no Controle Assinaturas está pausada "
        f"({ENV_PAUSE_CREATE}=true). Apenas vínculo, reparo e atualização."
    )
