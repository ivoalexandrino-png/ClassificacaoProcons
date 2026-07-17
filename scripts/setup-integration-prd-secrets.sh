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
CREDENTIALS_DIR="${ROOT_DIR}/credentials"
mkdir -p "${CREDENTIALS_DIR}"

OAUTH_FILE="${1:-${CREDENTIALS_DIR}/gmail-oauth.json}"
TOKEN_FILE="${2:-${CREDENTIALS_DIR}/gmail-token.json}"

if [[ -n "${GMAIL_OAUTH_JSON:-}" && ! -f "${OAUTH_FILE}" ]]; then
  printf '%s' "${GMAIL_OAUTH_JSON}" > "${OAUTH_FILE}"
fi
if [[ -n "${GMAIL_TOKEN_JSON:-}" && ! -f "${TOKEN_FILE}" ]]; then
  printf '%s' "${GMAIL_TOKEN_JSON}" > "${TOKEN_FILE}"
fi

MONDAY_TOKEN="${MONDAY_TOKEN:-${MONDAY_API_TOKEN:-}}"
AUTENTIQUE_TOKEN="${AUTENTIQUE_TOKEN:-${AUTENTIQUE_API_TOKEN:-}}"
GEMINI_KEY="${GEMINI_KEY:-${GEMINI_API_KEY:-}}"

export PATH="${HOME}/google-cloud-sdk/bin:${HOME}/google-cloud-sdk/google-cloud-sdk/bin:${PATH}"

gcloud config set project "${PROJECT_ID}" >/dev/null

enable_api() {
  local api="$1"
  if gcloud services enable "${api}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "API ativa: ${api}"
  else
    echo "Aviso: não foi possível ativar ${api} (habilite manualmente no Console GCP)" >&2
  fi
}

enable_api secretmanager.googleapis.com
enable_api run.googleapis.com
enable_api cloudbuild.googleapis.com
enable_api artifactregistry.googleapis.com

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
