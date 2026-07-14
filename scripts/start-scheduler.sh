#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION_NAME="procon-scheduler"
TMUX_CONF="${TMUX_CONF:-/exec-daemon/tmux.portal.conf}"

chmod +x "${ROOT_DIR}/scripts/run-pipeline.sh"
chmod +x "${ROOT_DIR}/scripts/run-scheduler.sh"

if tmux -f "${TMUX_CONF}" has-session -t "=${SESSION_NAME}" 2>/dev/null; then
  echo "Agendador já está rodando (sessão tmux: ${SESSION_NAME})."
  exit 0
fi

tmux -f "${TMUX_CONF}" new-session -d -s "${SESSION_NAME}" -c "${ROOT_DIR}" -- \
  "${SHELL:-bash}" -lc "${ROOT_DIR}/scripts/run-scheduler.sh"

echo "Agendador iniciado. Roda a cada 1 hora."
echo "Logs: ${ROOT_DIR}/logs/pipeline.log e logs/scheduler.log"
echo ""
echo "Para ver status: tmux -f ${TMUX_CONF} attach-session -t ${SESSION_NAME}"
echo "Para parar: tmux -f ${TMUX_CONF} kill-session -t ${SESSION_NAME}"
