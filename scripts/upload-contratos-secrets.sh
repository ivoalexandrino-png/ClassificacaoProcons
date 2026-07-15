#!/usr/bin/env bash
# Envia credenciais do fluxo de contratos para o Secret Manager (uso único).
#
# Uso:
#   PROJECT_ID=seu-projeto bash scripts/upload-contratos-secrets.sh
#
# Antes de rodar, crie os arquivos em credentials/ (não commitar):
#   - contratos-monday-token.txt
#   - contratos-autentique-token.txt
#   - contratos-gemini-key.txt
#   - contratos-autentique-webhook-secret.txt  (preencher após registrar webhook)

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

upload_secret "contratos-monday-token" "${ROOT_DIR}/credentials/contratos-monday-token.txt"
upload_secret "contratos-autentique-token" "${ROOT_DIR}/credentials/contratos-autentique-token.txt"
upload_secret "contratos-gemini-key" "${ROOT_DIR}/credentials/contratos-gemini-key.txt"

if [[ -f "${ROOT_DIR}/credentials/contratos-autentique-webhook-secret.txt" ]]; then
  upload_secret "contratos-autentique-webhook-secret" \
    "${ROOT_DIR}/credentials/contratos-autentique-webhook-secret.txt"
else
  echo "Pule contratos-autentique-webhook-secret por ora (criar após registrar webhook no Autentique)."
fi

echo ""
echo "Secrets de contratos enviados para o projeto ${PROJECT_ID}."
