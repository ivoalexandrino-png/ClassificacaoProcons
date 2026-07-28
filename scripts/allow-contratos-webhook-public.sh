#!/usr/bin/env bash
# Permite POST público no Cloud Run (webhooks Autentique/Monday).
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Defina PROJECT_ID}"
REGION="${REGION:-southamerica-east1}"
SERVICE_NAME="${SERVICE_NAME:-contratos-webhook}"

export PATH="${HOME}/google-cloud-sdk/bin:${HOME}/google-cloud-sdk/google-cloud-sdk/bin:${PATH}"

gcloud config set project "${PROJECT_ID}" >/dev/null

echo "==> IAM invoker público: ${SERVICE_NAME} (${REGION})"
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --member="allUsers" \
  --role="roles/run.invoker" \
  --quiet

echo "OK: tráfego não autenticado permitido em ${SERVICE_NAME}"
