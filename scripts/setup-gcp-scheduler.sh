#!/usr/bin/env bash
# Configura Cloud Scheduler para rodar o worker a cada 1 hora (24h).
#
# Pré-requisitos:
#   - gcloud autenticado
#   - Cloud Run Job "classificacao-procons-worker" já deployado
#   - APIs habilitadas: run, cloudscheduler
#
# Uso:
#   PROJECT_ID=seu-projeto REGION=southamerica-east1 bash scripts/setup-gcp-scheduler.sh

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Defina PROJECT_ID}"
REGION="${REGION:-southamerica-east1}"
JOB_NAME="${JOB_NAME:-classificacao-procons-worker}"
SCHEDULER_NAME="${SCHEDULER_NAME:-classificacao-procons-hourly}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-classificacao-procons-scheduler@${PROJECT_ID}.iam.gserviceaccount.com}"

echo "Habilitando APIs..."
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com --project="${PROJECT_ID}"

echo "Criando service account do agendador (se não existir)..."
gcloud iam service-accounts create classificacao-procons-scheduler \
  --project="${PROJECT_ID}" \
  --display-name="Classificacao Procons Scheduler" 2>/dev/null || true

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/run.developer" \
  --quiet

RUN_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

if gcloud scheduler jobs describe "${SCHEDULER_NAME}" --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Atualizando agendador existente..."
  gcloud scheduler jobs update http "${SCHEDULER_NAME}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}" \
    --schedule="0 * * * *" \
    --time-zone="America/Sao_Paulo" \
    --uri="${RUN_URI}" \
    --http-method=POST \
    --oauth-service-account-email="${SERVICE_ACCOUNT}" \
    --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform"
else
  echo "Criando agendador horário..."
  gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}" \
    --schedule="0 * * * *" \
    --time-zone="America/Sao_Paulo" \
    --uri="${RUN_URI}" \
    --http-method=POST \
    --oauth-service-account-email="${SERVICE_ACCOUNT}" \
    --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform"
fi

echo ""
echo "Pronto! O worker rodará a cada 1 hora (fuso America/Sao_Paulo)."
echo "Testar agora:"
echo "  gcloud scheduler jobs run ${SCHEDULER_NAME} --location=${REGION} --project=${PROJECT_ID}"
