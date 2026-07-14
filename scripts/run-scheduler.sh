#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INTERVAL_SECONDS="${PROCON_INTERVAL_SECONDS:-3600}"
LOG_DIR="${ROOT_DIR}/logs"
LOG_FILE="${LOG_DIR}/scheduler.log"

mkdir -p "${LOG_DIR}"

echo "Agendador Procon iniciado. Intervalo: ${INTERVAL_SECONDS}s" | tee -a "${LOG_FILE}"

while true; do
  echo "----------------------------------------" >> "${LOG_FILE}"
  echo "Execução: $(date -u '+%Y-%m-%d %H:%M:%S UTC')" >> "${LOG_FILE}"
  "${ROOT_DIR}/scripts/run-pipeline.sh" || true
  echo "Próxima execução em ${INTERVAL_SECONDS}s" >> "${LOG_FILE}"
  sleep "${INTERVAL_SECONDS}"
done
