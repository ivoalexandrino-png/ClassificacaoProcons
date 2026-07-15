#!/usr/bin/env bash
set -euo pipefail

mkdir -p /app/credentials /app/downloads /app/data /app/logs

if [[ -n "${GMAIL_OAUTH_JSON:-}" ]]; then
  printf '%s' "${GMAIL_OAUTH_JSON}" > /app/credentials/gmail-oauth.json
fi

if [[ -n "${GMAIL_TOKEN_JSON:-}" ]]; then
  printf '%s' "${GMAIL_TOKEN_JSON}" > /app/credentials/gmail-token.json
fi

if [[ ! -f /app/credentials/gmail-token.json ]]; then
  echo "Erro: token do Google não configurado." >&2
  exit 1
fi

case "${1:-process}" in
  process)
    exec python3 -m classificacao_procons.cli process --max-results "${PROCON_MAX_RESULTS:-20}"
    ;;
  contratos-webhook)
    shift
    exec contratos-webhook serve --host 0.0.0.0 --port "${PORT:-8080}" "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
