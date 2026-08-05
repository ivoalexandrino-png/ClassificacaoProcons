"""Regras e checagens de alinhamento da resposta ao relato do SAC."""

from __future__ import annotations

_SAC_PLACEHOLDER_MARKERS = (
    "texto não extraído automaticamente",
    "falha ao baixar",
)


def effective_sac_text_length(sac_summary: str) -> int:
    """Quantidade de texto útil do SAC (ignora placeholders de anexo ilegível)."""
    if not sac_summary.strip():
        return 0
    kept: list[str] = []
    for line in sac_summary.splitlines():
        lowered = line.casefold()
        if any(marker in lowered for marker in _SAC_PLACEHOLDER_MARKERS):
            continue
        if line.strip().startswith("### ") and len(line.strip()) < 40:
            continue
        kept.append(line)
    return len("\n".join(kept).strip())


def should_run_sac_consistency_pass(sac_summary: str, *, min_chars: int = 120) -> bool:
    return effective_sac_text_length(sac_summary) >= min_chars
