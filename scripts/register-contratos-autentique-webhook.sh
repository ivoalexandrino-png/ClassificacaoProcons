#!/usr/bin/env bash
# Registra webhooks no Autentique e grava secret no Secret Manager (se retornado).
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Defina PROJECT_ID}"
REGION="${REGION:-southamerica-east1}"
SERVICE_NAME="${SERVICE_NAME:-contratos-webhook}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export PATH="${HOME}/google-cloud-sdk/bin:${HOME}/google-cloud-sdk/google-cloud-sdk/bin:${PATH}"

gcloud config set project "${PROJECT_ID}" >/dev/null

if [[ -z "${SERVICE_URL:-}" ]]; then
  SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format='value(status.url)')"
fi

echo "==> URL do serviço: ${SERVICE_URL}"

RESULT_JSON="$(contratos-webhook register-autentique-webhook --base-url "${SERVICE_URL}")"
echo "${RESULT_JSON}"

SECRET="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("webhook_secret") or "")' <<<"${RESULT_JSON}")"

if [[ -n "${SECRET}" ]]; then
  echo "==> Gravando contratos-autentique-webhook-secret no Secret Manager"
  if gcloud secrets describe contratos-autentique-webhook-secret --project="${PROJECT_ID}" >/dev/null 2>&1; then
    printf '%s' "${SECRET}" | gcloud secrets versions add contratos-autentique-webhook-secret \
      --project="${PROJECT_ID}" --data-file=- >/dev/null
  else
    printf '%s' "${SECRET}" | gcloud secrets create contratos-autentique-webhook-secret \
      --project="${PROJECT_ID}" --data-file=- >/dev/null
  fi
  echo "==> Redeploy com validação HMAC"
  PROJECT_ID="${PROJECT_ID}" REGION="${REGION}" bash "${ROOT_DIR}/scripts/deploy-contratos-cloud-run.sh"
else
  echo "==> Secret não retornado (endpoints já existiam); deploy completo opcional."
fi
