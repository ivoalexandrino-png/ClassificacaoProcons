#!/usr/bin/env bash
# Envia credenciais Google para o Secret Manager (uso único).
#
# Uso:
#   PROJECT_ID=seu-projeto bash scripts/upload-gcp-secrets.sh

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Defina PROJECT_ID}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

gcloud services enable secretmanager.googleapis.com --project="${PROJECT_ID}"

upload_secret() {
  local name="$1"
  local file="$2"
  if [[ ! -f "${file}" ]]; then
    echo "Arquivo não encontrado: ${file}" >&2
    exit 1
  fi
  if gcloud secrets describe "${name}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud secrets versions add "${name}" --project="${PROJECT_ID}" --data-file="${file}"
  else
    gcloud secrets create "${name}" --project="${PROJECT_ID}" --data-file="${file}"
  fi
  echo "Secret atualizado: ${name}"
}

upload_secret "procon-gmail-oauth" "${ROOT_DIR}/credentials/gmail-oauth.json"
upload_secret "procon-gmail-token" "${ROOT_DIR}/credentials/gmail-token.json"

echo ""
echo "Secrets criados no projeto ${PROJECT_ID}."
