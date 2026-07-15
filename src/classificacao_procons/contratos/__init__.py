"""Automação pós-assinatura de contratos (Autentique → Drive → Monday)."""

from classificacao_procons.contratos.pipeline import (
    ContractPipelineError,
    ContractPipelineOptions,
    process_finished_document,
)

__all__ = [
    "ContractPipelineError",
    "ContractPipelineOptions",
    "process_finished_document",
]
