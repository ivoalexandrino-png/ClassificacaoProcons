"""Disposições de fonte e classificações Sunday da migração."""

from __future__ import annotations

from enum import StrEnum


class Disposition(StrEnum):
    """O que fazer com cada source row (linha do Monday) na migração.

    A soma das contagens de todas as disposições deve igualar o total de source
    rows do snapshot (conservação — ver ``accounting``).
    """

    CREATE = "CREATE"
    ADOPT = "ADOPT"
    ABSORB = "ABSORB"
    EXCLUDE_TEST = "EXCLUDE_TEST"
    MANUAL = "MANUAL"
    ERROR = "ERROR"


#: Disposições que **não** criam um item Sunday novo.
NON_CREATING_DISPOSITIONS: frozenset[Disposition] = frozenset(
    {
        Disposition.ADOPT,
        Disposition.ABSORB,
        Disposition.EXCLUDE_TEST,
        Disposition.MANUAL,
        Disposition.ERROR,
    },
)

#: A única disposição que gera um item Sunday novo.
CREATING_DISPOSITIONS: frozenset[Disposition] = frozenset({Disposition.CREATE})

#: Todas as disposições que entram na fórmula de conservação.
ALL_DISPOSITIONS: tuple[Disposition, ...] = tuple(Disposition)


class SundayClassification(StrEnum):
    """Classificação de itens do lado Sunday sem source row Monday correspondente."""

    #: Item nasceu no Sunday; preservar, não excluir, não inventar Monday ID e
    #: **não** contar no denominador de source rows Monday.
    SUNDAY_NATIVE = "SUNDAY_NATIVE"
