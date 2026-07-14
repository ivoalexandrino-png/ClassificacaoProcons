#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs"
LOG_FILE="${LOG_DIR}/pipeline.log"

mkdir -p "${LOG_DIR}"

{
  echo "========================================"
  echo "Início: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  cd "${ROOT_DIR}"

  if ! python3 -m classificacao_procons.cli process --max-results 20; then
    echo "Aviso: processamento terminou com erros."
    exit 1
  fi

  echo "Fim: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
} >> "${LOG_FILE}" 2>&1
