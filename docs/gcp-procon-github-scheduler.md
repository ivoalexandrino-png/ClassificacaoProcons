# Cloud Scheduler → GitHub Actions (Procon)

Backup quando o cron nativo do GitHub Actions atrasa ou pula janelas (e-mail → Monday com atraso de horas).

## O que é criado

| Job (nome padrão) | Agenda (Brasília) | Workflow dispatch |
|-------------------|-------------------|-------------------|
| `procon-github-dispatch-process-30m` | `*/30 * * * *` | `skip_elaborate=true` |
| `procon-github-dispatch-elaborate-hourly` | `15 * * * *` | `skip_elaborate=false` |

Alvo: workflow **Procon automation (every 30 min)** (`procon-hourly.yml`), branch `main`.

## Pré-requisitos

1. **Projeto GCP** (staging primeiro): `b4a-prj-*-stg` com billing ativo.
2. **PAT fine-grained** (`GITHUB_ACTIONS_PAT`):
   - Repositório: `ClassificacaoProcons`
   - Permissão **Actions: Read and write**
   - Criar em: https://github.com/settings/personal-access-tokens/new
3. `gcloud` autenticado: `gcloud auth login` e `gcloud config set project PROJECT_ID`

## Instalação (uma vez)

### Opção A — PAT só na hora do setup (mais simples)

```bash
export GITHUB_ACTIONS_PAT="github_pat_..."
export PROJECT_ID="b4a-prj-SEU-SLUG-stg"
export REGION="southamerica-east1"

bash scripts/setup-gcp-github-procon-scheduler.sh
```

O PAT fica no header do job do Scheduler (visível para quem tem `cloudscheduler.jobs.get` no projeto). Rotacione o PAT e rode o script de novo para atualizar.

### Opção B — PAT no Secret Manager (recomendado produção)

```bash
export PROJECT_ID="b4a-prj-SEU-SLUG-stg"

echo -n "$GITHUB_ACTIONS_PAT" | gcloud secrets create github-actions-pat-procon \
  --project="${PROJECT_ID}" \
  --replication-policy="automatic" \
  --data-file=-

export GITHUB_PAT_SECRET="github-actions-pat-procon"
bash scripts/setup-gcp-github-procon-scheduler.sh
```

Conceda ao usuário/sa que roda o script `secretAccessor` no secret, se necessário.

## Teste

```bash
gcloud scheduler jobs run procon-github-dispatch-process-30m \
  --location=southamerica-east1 \
  --project="${PROJECT_ID}"
```

No GitHub:

```bash
gh run list --workflow="Procon automation (every 30 min)" --limit 5
```

Deve aparecer um run com evento `workflow_dispatch` em até 1–2 minutos.

## Variáveis opcionais

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `ENABLE_ELABORATE_JOB` | `true` | Cria job horário com elaborate |
| `GITHUB_OWNER` | `ivoalexandrino-png` | Dono do repo |
| `GITHUB_REPO` | `ClassificacaoProcons` | Nome do repo |
| `GITHUB_REF` | `main` | Branch disparada |
| `JOB_PROCESS` / `JOB_ELABORATE` | ver script | Nomes dos jobs |

## Produção

Repita o mesmo script no projeto `-prd` após validar em staging. Use secret separado ou versão nova do PAT.

## Remover

```bash
gcloud scheduler jobs delete procon-github-dispatch-process-30m --location="${REGION}" --project="${PROJECT_ID}" --quiet
gcloud scheduler jobs delete procon-github-dispatch-elaborate-hourly --location="${REGION}" --project="${PROJECT_ID}" --quiet
```
