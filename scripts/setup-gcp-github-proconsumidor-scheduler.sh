#!/usr/bin/env bash
# Backup ao cron do GitHub Actions: dispara "Proconsumidor local processing" via API.
# Útil quando o cron nativo atrasa (repositório privado). Exige runner self-hosted online.
#
# Uso:
#   export GITHUB_ACTIONS_PAT="github_pat_..."
#   PROJECT_ID=b4a-prj-xxx-stg REGION=southamerica-east1 bash scripts/setup-gcp-github-proconsumidor-scheduler.sh
#
# Opcional (PAT no Secret Manager):
#   GITHUB_PAT_SECRET=github-actions-pat-procon PROJECT_ID=... bash scripts/setup-gcp-github-proconsumidor-scheduler.sh

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Defina PROJECT_ID}"
REGION="${REGION:-southamerica-east1}"
GITHUB_OWNER="${GITHUB_OWNER:-ivoalexandrino-png}"
GITHUB_REPO="${GITHUB_REPO:-ClassificacaoProcons}"
WORKFLOW_FILE="${WORKFLOW_FILE:-procon-proconsumidor-local.yml}"
GITHUB_REF="${GITHUB_REF:-main}"
JOB_NAME="${JOB_NAME:-procon-github-dispatch-proconsumidor-30m}"
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

echo "Habilitando Cloud Scheduler API..."
gcloud services enable cloudscheduler.googleapis.com --project="${PROJECT_ID}"

GITHUB_PAT="$(resolve_pat)"
BODY_FILE="$(mktemp)"
trap 'rm -f "${BODY_FILE}"' EXIT
printf '{"ref":"%s","inputs":{"max_results":"20"}}' "${GITHUB_REF}" > "${BODY_FILE}"

if gcloud scheduler jobs describe "${JOB_NAME}" --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Atualizando job ${JOB_NAME}..."
  gcloud scheduler jobs update http "${JOB_NAME}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}" \
    --schedule="10,40 * * * *" \
    --time-zone="America/Sao_Paulo" \
    --uri="${DISPATCH_URI}" \
    --http-method=POST \
    --headers="Accept=application/vnd.github+json,Authorization=Bearer ${GITHUB_PAT},X-GitHub-Api-Version=2022-11-28,Content-Type=application/json" \
    --message-body-from-file="${BODY_FILE}"
else
  echo "Criando job ${JOB_NAME}..."
  gcloud scheduler jobs create http "${JOB_NAME}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}" \
    --schedule="10,40 * * * *" \
    --time-zone="America/Sao_Paulo" \
    --uri="${DISPATCH_URI}" \
    --http-method=POST \
    --headers="Accept=application/vnd.github+json,Authorization=Bearer ${GITHUB_PAT},X-GitHub-Api-Version=2022-11-28,Content-Type=application/json" \
    --message-body-from-file="${BODY_FILE}"
fi

echo ""
echo "Pronto. Job ${JOB_NAME} dispara o workflow Proconsumidor às :10 e :40 (Brasília)."
echo "Requer runner self-hosted com label procon-br (ver docs/procon-proconsumidor-runner.md)."
echo ""
echo "Testar:"
echo "  gcloud scheduler jobs run ${JOB_NAME} --location=${REGION} --project=${PROJECT_ID}"
