#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRON_LINE="0 * * * * ${ROOT_DIR}/scripts/run-pipeline.sh"

chmod +x "${ROOT_DIR}/scripts/run-pipeline.sh"

EXISTING="$(crontab -l 2>/dev/null || true)"
if echo "${EXISTING}" | grep -Fq "scripts/run-pipeline.sh"; then
  echo "Agendamento já existe."
else
  {
    echo "${EXISTING}"
    echo "${CRON_LINE}"
  } | crontab -
  echo "Agendamento criado: a cada hora (minuto 0)."
fi

echo ""
echo "Crontab atual:"
crontab -l
