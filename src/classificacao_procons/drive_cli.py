"""CLI para salvar PDFs no Google Drive."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from classificacao_procons.drive import DriveClientError, save_complaint_pdf
from classificacao_procons.google_auth import DEFAULT_DRIVE_PARENT_FOLDER_ID, has_drive_access


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Salva PDF de reclamação no Google Drive.")
    parser.add_argument("--consumer-name", required=True, help="Nome da consumidora.")
    parser.add_argument("--pdf", required=True, help="Caminho do PDF local.")
    parser.add_argument(
        "--parent-folder-id",
        default=DEFAULT_DRIVE_PARENT_FOLDER_ID,
        help="ID da pasta raiz no Drive.",
    )
    args = parser.parse_args(argv)

    if not has_drive_access():
        print(
            "Drive ainda não autorizado. Rode: procon-email auth",
            file=sys.stderr,
        )
        return 1

    try:
        result = save_complaint_pdf(
            consumer_name=args.consumer_name,
            pdf_path=args.pdf,
            parent_folder_id=args.parent_folder_id,
        )
    except DriveClientError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
