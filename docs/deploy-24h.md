# Deploy 24h no Google Cloud

Para rodar **de hora em hora, 24h por dia**, com o menor risco de parar.

## Como funciona (simples)

```
A cada 1 hora
    ↓
Google Cloud Scheduler (relógio do Google)
    ↓
Cloud Run Job (servidor que executa o processamento)
    ↓
E-mail → Portal → Drive
```

O Google cuida de ligar o servidor na hora certa. **Seu PC não precisa ficar ligado.**

## Passo a passo (uma vez só)

### 1. Definir o projeto Google

Use o mesmo projeto do OAuth (`sonic-cat-479513-b2`):

```bash
export PROJECT_ID=sonic-cat-479513-b2
export REGION=southamerica-east1
```

### 2. Enviar credenciais para o Secret Manager

```bash
bash scripts/upload-gcp-secrets.sh
```

### 3. Criar repositório de imagens Docker

```bash
gcloud artifacts repositories create classificacao-procons \
  --repository-format=docker \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

### 4. Fazer deploy do worker

```bash
gcloud builds submit --config=cloudbuild.yaml --project="${PROJECT_ID}"
```

### 5. Agendar para rodar a cada 1 hora

```bash
bash scripts/setup-gcp-scheduler.sh
```

### 6. Testar manualmente

```bash
gcloud scheduler jobs run classificacao-procons-hourly \
  --location="${REGION}" --project="${PROJECT_ID}"
```

## Ver logs

```bash
gcloud run jobs executions list \
  --job=classificacao-procons-worker \
  --region="${REGION}" --project="${PROJECT_ID}"
```

Ou no console: **Cloud Run → Jobs → classificacao-procons-worker → Logs**

## Quando o token Google expirar

Reautorize localmente (`procon-email auth`) e rode de novo:

```bash
bash scripts/upload-gcp-secrets.sh
```

## Custo estimado

Baixo: o servidor só liga durante o processamento (~alguns minutos por hora).
