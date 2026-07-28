#!/usr/bin/env bash
# Dispara o workflow GitHub "Procon automation (every 30 min)" via API (backup ao cron do Actions).
#
# Cria dois jobs no Cloud Scheduler (America/Sao_Paulo):
#   - A cada 30 min: process (skip_elaborate=true)
#   - A cada hora (:15): process + elaborate (skip_elaborate=false)
#
# Pré-requisitos:
#   - gcloud autenticado com permissão no projeto
#   - Fine-grained PAT com Actions: Read and write no repo ClassificacaoProcons
#
# Uso:
#   export GITHUB_ACTIONS_PAT="github_pat_..."
#   PROJECT_ID=b4a-prj-xxx-stg REGION=southamerica-east1 bash scripts/setup-gcp-github-procon-scheduler.sh
#
# Opcional: PAT no Secret Manager (recomendado em produção):
#   echo -n "$GITHUB_ACTIONS_PAT" | gcloud secrets create github-actions-pat-procon \
#     --project=PROJECT_ID --data-file=-
#   GITHUB_PAT_SECRET=github-actions-pat-procon PROJECT_ID=... bash scripts/setup-gcp-github-procon-scheduler.sh

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Defina PROJECT_ID}"
REGION="${REGION:-southamerica-east1}"
GITHUB_OWNER="${GITHUB_OWNER:-ivoalexandrino-png}"
GITHUB_REPO="${GITHUB_REPO:-ClassificacaoProcons}"
WORKFLOW_FILE="${WORKFLOW_FILE:-procon-hourly.yml}"
GITHUB_REF="${GITHUB_REF:-main}"

JOB_PROCESS="${JOB_PROCESS:-procon-github-dispatch-process-30m}"
JOB_ELABORATE="${JOB_ELABORATE:-procon-github-dispatch-elaborate-hourly}"
GITHUB_PAT_SECRET="${GITHUB_PAT_SECRET:-}"

DISPATCH_URI="https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches"

resolve_pat() {
  if [ -n "${GITHUB_ACTIONS_PAT:-}" ]; then
    printf '%s' "${GITHUB_ACTIONS_PAT}"
    return
  fi
  if [ -n "${GITHUB_PAT_SECRET}" ]; then
    gcloud secrets versions access latest \
      --secret="${GITHUB_PAT_SECRET}" \
      --project="${PROJECT_ID}"
    return
  fi
  echo "ERRO: defina GITHUB_ACTIONS_PAT ou GITHUB_PAT_SECRET." >&2
  exit 1
}

upsert_http_job() {
  local job_name="$1"
  local schedule="$2"
  local body_file="$3"

  if gcloud scheduler jobs describe "${job_name}" --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Atualizando job ${job_name}..."
    gcloud scheduler jobs update http "${job_name}" \
      --location="${REGION}" \
      --project="${PROJECT_ID}" \
      --schedule="${schedule}" \
      --time-zone="America/Sao_Paulo" \
      --uri="${DISPATCH_URI}" \
      --http-method=POST \
      --headers="Accept=application/vnd.github+json,Authorization=Bearer ${GITHUB_PAT},X-GitHub-Api-Version=2022-11-28,Content-Type=application/json" \
      --message-body-from-file="${body_file}"
  else
    echo "Criando job ${job_name}..."
    gcloud scheduler jobs create http "${job_name}" \
      --location="${REGION}" \
      --project="${PROJECT_ID}" \
      --schedule="${schedule}" \
      --time-zone="America/Sao_Paulo" \
      --uri="${DISPATCH_URI}" \
      --http-method=POST \
      --headers="Accept=application/vnd.github+json,Authorization=Bearer ${GITHUB_PAT},X-GitHub-Api-Version=2022-11-28,Content-Type=application/json" \
      --message-body-from-file="${body_file}"
  fi
}

echo "Habilitando Cloud Scheduler API..."
gcloud services enable cloudscheduler.googleapis.com --project="${PROJECT_ID}"

GITHUB_PAT="$(resolve_pat)"

if [ -n "${GITHUB_PAT_SECRET}" ] && [ -z "${GITHUB_ACTIONS_PAT:-}" ]; then
  echo "Usando PAT do Secret Manager: ${GITHUB_PAT_SECRET}"
else
  echo "Usando GITHUB_ACTIONS_PAT do ambiente."
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

printf '{"ref":"%s","inputs":{"skip_elaborate":"true"}}' "${GITHUB_REF}" > "${TMP_DIR}/body-process.json"
printf '{"ref":"%s","inputs":{"skip_elaborate":"false"}}' "${GITHUB_REF}" > "${TMP_DIR}/body-elaborate.json"

upsert_http_job "${JOB_PROCESS}" "*/30 * * * *" "${TMP_DIR}/body-process.json"

if [ "${ENABLE_ELABORATE_JOB:-true}" = "true" ]; then
  upsert_http_job "${JOB_ELABORATE}" "15 * * * *" "${TMP_DIR}/body-elaborate.json"
fi

echo ""
echo "Pronto. Jobs no projeto ${PROJECT_ID} (${REGION}):"
echo "  - ${JOB_PROCESS}: a cada 30 min (só process → Monday)"
if [ "${ENABLE_ELABORATE_JOB:-true}" = "true" ]; then
  echo "  - ${JOB_ELABORATE}: minuto :15 de cada hora (process + elaborate)"
fi
echo ""
echo "Testar agora (process):"
echo "  gcloud scheduler jobs run ${JOB_PROCESS} --location=${REGION} --project=${PROJECT_ID}"
echo ""
echo "Conferir no GitHub:"
echo "  gh run list --workflow=\"Procon automation (every 30 min)\" --limit 5"
