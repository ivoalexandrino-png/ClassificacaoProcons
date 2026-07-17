#!/usr/bin/env bash
# Deploy do serviço contratos-webhook no Cloud Run.
#
# Uso (recomendado: Google Cloud Shell do projeto):
#   PROJECT_ID=b4a-prj-integration-prd bash scripts/deploy-contratos-cloud-run.sh
#
# Pré-requisitos no Secret Manager (mesmo projeto):
#   - procon-gmail-oauth
#   - procon-gmail-token
#   - contratos-monday-token
#   - contratos-autentique-token
#   - contratos-gemini-key
#   - contratos-autentique-webhook-secret (opcional até registrar webhook no Autentique)

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Defina PROJECT_ID}"
REGION="${REGION:-southamerica-east1}"
ARTIFACT_REPO="${ARTIFACT_REPO:-classificacao-procons}"
SERVICE_NAME="${SERVICE_NAME:-contratos-webhook}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export PATH="${HOME}/google-cloud-sdk/bin:${HOME}/google-cloud-sdk/google-cloud-sdk/bin:${PATH}"

echo "==> Projeto: ${PROJECT_ID}"
echo "==> Região:  ${REGION}"

gcloud config set project "${PROJECT_ID}"

echo "==> Habilitando APIs (se tiver permissão)..."
for api in run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com; do
  if gcloud services enable "${api}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "API ativa: ${api}"
  else
    echo "Aviso: ative manualmente no Console: ${api}" >&2
  fi
done

echo "==> Verificando secrets obrigatórios..."
REQUIRED_SECRETS=(
  procon-gmail-oauth
  procon-gmail-token
  contratos-monday-token
  contratos-autentique-token
  contratos-gemini-key
)
MISSING=()
for secret in "${REQUIRED_SECRETS[@]}"; do
  if ! gcloud secrets describe "${secret}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    MISSING+=("${secret}")
  fi
done
if ((${#MISSING[@]} > 0)); then
  echo "Secrets ausentes no Secret Manager:" >&2
  printf '  - %s\n' "${MISSING[@]}" >&2
  echo "" >&2
  echo "Crie os arquivos em credentials/ e rode:" >&2
  echo "  PROJECT_ID=${PROJECT_ID} bash scripts/upload-contratos-secrets.sh" >&2
  exit 1
fi

HAS_WEBHOOK_SECRET=false
if gcloud secrets describe contratos-autentique-webhook-secret --project="${PROJECT_ID}" >/dev/null 2>&1; then
  HAS_WEBHOOK_SECRET=true
  echo "==> Secret do webhook Autentique: OK"
else
  echo "==> Secret contratos-autentique-webhook-secret ausente (deploy segue sem validação HMAC)"
fi

echo "==> Verificando Artifact Registry..."
if ! gcloud artifacts repositories describe "${ARTIFACT_REPO}" \
  --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "==> Criando repositório ${ARTIFACT_REPO}..."
  gcloud artifacts repositories create "${ARTIFACT_REPO}" \
    --repository-format=docker \
    --location="${REGION}" \
    --project="${PROJECT_ID}"
fi

BUILD_CONFIG="${ROOT_DIR}/cloudbuild-contratos.yaml"
if [[ "${HAS_WEBHOOK_SECRET}" != "true" ]]; then
  BUILD_CONFIG="${ROOT_DIR}/cloudbuild-contratos-initial.yaml"
fi

echo "==> Build + deploy (${BUILD_CONFIG})..."
gcloud builds submit \
  --config="${BUILD_CONFIG}" \
  --project="${PROJECT_ID}" \
  "${ROOT_DIR}"

echo ""
echo "==> URL do serviço:"
SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format='value(status.url)')"
echo "${SERVICE_URL}"
echo ""
echo "Webhook Autentique:"
echo "  ${SERVICE_URL}/webhooks/autentique"
echo ""
echo "Webhook Monday (Contratos):"
echo "  ${SERVICE_URL/webhooks/autentique/webhooks/monday}"
