#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRON_LINE="5 * * * * cd ${ROOT_DIR} && MONDAY_API_TOKEN=\$MONDAY_API_TOKEN ${ROOT_DIR}/scripts/run-proconsumidor-process.sh >> ${ROOT_DIR}/logs/proconsumidor.log 2>&1"

chmod +x "${ROOT_DIR}/scripts/run-proconsumidor-process.sh"
mkdir -p "${ROOT_DIR}/logs"

EXISTING="$(crontab -l 2>/dev/null || true)"
if echo "${EXISTING}" | grep -Fq "run-proconsumidor-process.sh"; then
  echo "Agendamento Proconsumidor já existe."
else
  {
    echo "${EXISTING}"
    echo "${CRON_LINE}"
  } | crontab -
  echo "Agendamento criado: a cada hora no minuto 5."
fi

echo ""
echo "Certifique-se de exportar MONDAY_API_TOKEN no seu shell profile."
echo "Crontab atual:"
crontab -l
