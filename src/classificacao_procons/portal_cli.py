"""CLI do portal Procon-SP."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from classificacao_procons.portal import PortalFetchOptions, ProconPortalError, fetch_complaint


def _serialize_complaint(complaint: object) -> dict[str, object]:
    data = asdict(complaint)
    for key in ("complaint_date", "response_deadline"):
        if data.get(key) is not None:
            data[key] = data[key].isoformat()
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acessa o portal Procon-SP.")
    parser.add_argument("--code", required=True, help="Código de acesso do e-mail do Procon.")
    parser.add_argument(
        "--download-dir",
        default="downloads",
        help="Pasta para salvar o PDF (padrão: downloads).",
    )
    args = parser.parse_args(argv)

    try:
        complaint = fetch_complaint(
            PortalFetchOptions(
                access_code=args.code,
                download_dir=Path(args.download_dir),
            ),
        )
    except ProconPortalError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    print(json.dumps(_serialize_complaint(complaint), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
