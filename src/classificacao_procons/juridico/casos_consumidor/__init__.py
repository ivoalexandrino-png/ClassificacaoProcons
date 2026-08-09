"""Inteligência de casos de consumidor (tema, condenação, benchmark)."""

from classificacao_procons.juridico.casos_consumidor.models import (
    CaseTheme,
    CasosScanResult,
    ConsumerCaseInsight,
)
from classificacao_procons.juridico.casos_consumidor.pipeline import (
    CasosScanOptions,
    scan_consumer_cases,
)

__all__ = [
    "CaseTheme",
    "CasosScanOptions",
    "CasosScanResult",
    "ConsumerCaseInsight",
    "scan_consumer_cases",
]
