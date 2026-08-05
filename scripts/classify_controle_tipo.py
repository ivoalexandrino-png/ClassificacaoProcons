#!/usr/bin/env python3
"""Dry-run: classifica Tipo (heurística como pista + Gemini no PDF para gravar Tipo)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from classificacao_procons.contratos.controle_tipo import (  # noqa: E402
    classify_controle_tipo_heuristic,
    classify_controle_tipo_with_gemini,
    resolve_controle_tipo_label,
    supplier_title_requires_pdf_analysis,
    document_requires_pdf_analysis,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Classificar coluna Tipo do Controle")
    parser.add_argument("document_name", help="Título do documento (Autentique)")
    parser.add_argument("--pdf", type=Path, help="PDF para classificação Gemini")
    parser.add_argument("--skip-gemini", action="store_true")
    args = parser.parse_args()

    heuristic = classify_controle_tipo_heuristic(document_name=args.document_name)
    payload: dict[str, object] = {
        "heuristic": heuristic.__dict__,
        "requires_pdf_analysis": document_requires_pdf_analysis(
            document_name=args.document_name,
        ),
    }

    if args.pdf:
        if not args.skip_gemini:
            try:
                gemini = classify_controle_tipo_with_gemini(
                    pdf_path=args.pdf,
                    document_name=args.document_name,
                )
                payload["gemini"] = gemini.__dict__
            except Exception as exc:  # noqa: BLE001 — CLI
                payload["gemini_error"] = str(exc)
        resolved = resolve_controle_tipo_label(
            document_name=args.document_name,
            pdf_path=args.pdf,
            skip_gemini=args.skip_gemini,
        )
    else:
        resolved = resolve_controle_tipo_label(
            document_name=args.document_name,
            min_confidence="low",
        )

    payload["resolved_tipo"] = resolved
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
