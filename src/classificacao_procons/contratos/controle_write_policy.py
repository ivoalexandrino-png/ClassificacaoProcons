"""Kill switch global de escrita Monday para Controle Assinaturas (Autentique → Controle)."""

from __future__ import annotations

import os

ENV_CONTROLE_WRITE_ENABLED = "CONTROLE_WRITE_ENABLED"
_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})


class ControleWriteForbiddenError(RuntimeError):
    """Mutation no Controle bloqueada (compare e leituras continuam permitidos)."""


def is_controle_write_enabled(*, allow_write: bool | None = None) -> bool:
    """True quando create/update/link/archive/reconcile desta integração podem gravar no Monday."""
    if allow_write is False:
        return False
    if allow_write is True:
        return True
    raw = os.environ.get(ENV_CONTROLE_WRITE_ENABLED, "false").strip().casefold()
    return raw in _ENABLED_VALUES


def require_controle_write_enabled(*, allow_write: bool | None = None) -> None:
    if not is_controle_write_enabled(allow_write=allow_write):
        raise ControleWriteForbiddenError(
            "Escrita no Controle Assinaturas desabilitada "
            f"({ENV_CONTROLE_WRITE_ENABLED} não está ativo). "
            "Compare e diagnósticos continuam disponíveis."
        )


def controle_write_disabled_message() -> str:
    return (
        f"Escrita no Controle Assinaturas desabilitada ({ENV_CONTROLE_WRITE_ENABLED}=false)."
    )
