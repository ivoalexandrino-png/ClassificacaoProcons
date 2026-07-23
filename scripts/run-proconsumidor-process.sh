#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f credentials/gmail-token.json ]]; then
  echo "ERRO: credentials/gmail-token.json ausente. Rode: procon-email auth"
  exit 1
fi

if [[ -z "${MONDAY_API_TOKEN:-}" ]]; then
  echo "ERRO: MONDAY_API_TOKEN não definida."
  echo "Exemplo: export MONDAY_API_TOKEN=seu_token"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERRO: python3 não encontrado."
  exit 1
fi

python3 -m pip install -e ".[dev]" >/dev/null
python3 -m playwright install chromium >/dev/null

HTTP_STATUS="$(curl -s -o /dev/null -w "%{http_code}" "https://proconsumidor.mj.gov.br/" || true)"
if [[ "${HTTP_STATUS}" == "403" ]]; then
  echo "AVISO: este IP está bloqueado pelo portal (HTTP 403)."
  echo "Rode este script em um Mac/PC no Brasil (não em cloud/datacenter)."
  exit 1
fi

echo "Portal acessível (HTTP ${HTTP_STATUS}). Processando e-mails Proconsumidor..."
python3 -m classificacao_procons.cli process --sources proconsumidor --max-results 20
