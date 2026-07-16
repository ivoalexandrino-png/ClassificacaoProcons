#!/usr/bin/env python3
"""Cria coluna 'Contrato relacionado' no Controle Assinaturas (Monday)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from classificacao_procons.contratos.monday_setup import (  # noqa: E402
    CONTROLE_COL_CONTRATO_RELACIONADO_TITLE,
    ensure_controle_contrato_relacionado_column,
)
from classificacao_procons.monday.client import (  # noqa: E402
    MondayClientError,
    get_api_token_from_env,
)


def main() -> int:
    token = get_api_token_from_env()
    if not token:
        print("MONDAY_API_TOKEN não configurada.", file=sys.stderr)
        return 1

    try:
        result = ensure_controle_contrato_relacionado_column(api_token=token)
    except MondayClientError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    payload = {
        "column_id": result.column_id,
        "column_title": CONTROLE_COL_CONTRATO_RELACIONADO_TITLE,
        "board_id": result.board_id,
        "created": result.created,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
