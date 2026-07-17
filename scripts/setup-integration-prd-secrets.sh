#!/usr/bin/env bash
# Sobe os secrets do fluxo de contratos no projeto integration-prd.
#
# Uso no Cloud Shell (depois de fazer upload dos JSONs):
#   bash scripts/setup-integration-prd-secrets.sh ~/client_secret_....json ~/gmail-token.json
#
# Ou, se os arquivos estiverem em credentials/:
#   bash scripts/setup-integration-prd-secrets.sh

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-b4a-prj-integration-prd}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

OAUTH_FILE="${1:-${ROOT_DIR}/credentials/gmail-oauth.json}"
TOKEN_FILE="${2:-${ROOT_DIR}/credentials/gmail-token.json}"

export PATH="${HOME}/google-cloud-sdk/bin:${HOME}/google-cloud-sdk/google-cloud-sdk/bin:${PATH}"

gcloud config set project "${PROJECT_ID}" >/dev/null
gcloud services enable secretmanager.googleapis.com --project="${PROJECT_ID}" >/dev/null

upsert_secret() {
  local name="$1"
  local file="$2"
  if [[ ! -f "${file}" ]]; then
    echo "Arquivo não encontrado: ${file}" >&2
    exit 1
  fi
  if gcloud secrets describe "${name}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud secrets versions add "${name}" --project="${PROJECT_ID}" --data-file="${file}" >/dev/null
    echo "Atualizado: ${name}"
  else
    gcloud secrets create "${name}" --project="${PROJECT_ID}" --data-file="${file}" >/dev/null
    echo "Criado: ${name}"
  fi
}

upsert_text_secret() {
  local name="$1"
  local value="$2"
  if [[ -z "${value}" ]]; then
    echo "Pule ${name} (variável vazia)"
    return
  fi
  if gcloud secrets describe "${name}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    printf '%s' "${value}" | gcloud secrets versions add "${name}" --project="${PROJECT_ID}" --data-file=- >/dev/null
    echo "Atualizado: ${name}"
  else
    printf '%s' "${value}" | gcloud secrets create "${name}" --project="${PROJECT_ID}" --data-file=- >/dev/null
    echo "Criado: ${name}"
  fi
}

echo "==> Projeto: ${PROJECT_ID}"
echo "==> OAuth:   ${OAUTH_FILE}"
echo "==> Token:   ${TOKEN_FILE}"

upsert_secret "procon-gmail-oauth" "${OAUTH_FILE}"
upsert_secret "procon-gmail-token" "${TOKEN_FILE}"

# Opcional: tokens de texto via variáveis de ambiente (não cole no chat)
upsert_text_secret "contratos-monday-token" "${MONDAY_TOKEN:-}"
upsert_text_secret "contratos-autentique-token" "${AUTENTIQUE_TOKEN:-}"
upsert_text_secret "contratos-gemini-key" "${GEMINI_KEY:-}"

echo ""
echo "Secrets no projeto:"
gcloud secrets list --project="${PROJECT_ID}" --filter="name:(procon-gmail OR contratos-)" --format="table(name)"

echo ""
echo "Próximo passo:"
echo "  PROJECT_ID=${PROJECT_ID} bash scripts/deploy-contratos-cloud-run.sh"
