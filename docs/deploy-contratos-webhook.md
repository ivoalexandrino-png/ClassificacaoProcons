# Deploy do webhook de contratos (Cloud Run)

Guia para o time de TI publicar o serviço que recebe avisos do Autentique.

## O que este serviço faz

Fica na internet 24h escutando o evento `document.finished` do Autentique. Quando um contrato é totalmente assinado:

1. Baixa o PDF assinado
2. Extrai dados com Gemini
3. Salva no Google Drive (pasta Contratos)
4. Atualiza Monday (Controle Assinaturas + Contratos)

## Pré-requisitos GCP

- Projeto GCP da B4A (staging primeiro)
- APIs: Cloud Run, Cloud Build, Artifact Registry, Secret Manager
- Secrets Google já existentes: `procon-gmail-oauth`, `procon-gmail-token`

## Passo 1 — Criar secrets no Secret Manager

No computador do TI, criar arquivos temporários (não commitar):

| Arquivo local | Secret no GCP |
|---------------|---------------|
| `credentials/contratos-monday-token.txt` | `contratos-monday-token` |
| `credentials/contratos-autentique-token.txt` | `contratos-autentique-token` |
| `credentials/contratos-gemini-key.txt` | `contratos-gemini-key` |

Rodar:

```bash
PROJECT_ID=b4a-prj-SEU-SLUG-stg bash scripts/upload-contratos-secrets.sh
```

> O secret `contratos-autentique-webhook-secret` pode ser criado depois, quando o jurídico registrar o webhook no Autentique.

## Passo 2 — Deploy no Cloud Run

```bash
gcloud builds submit --config=cloudbuild-contratos.yaml --project=PROJECT_ID
```

Ao final, o comando imprime a URL do serviço, por exemplo:

`https://contratos-webhook-XXXXX-southamerica-east1.run.app`

**URL do webhook para o Autentique:**

```
https://contratos-webhook-XXXXX-southamerica-east1.run.app/webhooks/autentique
```

Enviar esta URL ao jurídico.

## Passo 3 — Jurídico registra no Autentique

1. https://painel.autentique.com.br → Perfil → Webhooks
2. Novo endpoint
3. URL: a URL acima
4. Evento: `document.finished`
5. Copiar o **secret** gerado
6. Salvar no Secret Manager:

```bash
echo -n "SECRET_COPIADO" > credentials/contratos-autentique-webhook-secret.txt
PROJECT_ID=... bash scripts/upload-contratos-secrets.sh
```

7. Redeploy para carregar o secret:

```bash
gcloud builds submit --config=cloudbuild-contratos.yaml --project=PROJECT_ID
```

## Passo 4 — Teste

Assinar um contrato de teste no Autentique (ou reenviar evento de teste no painel de webhooks).

Verificar:

- PDF na pasta correta do Drive
- Item no Monday Controle Assinaturas → Assinado
- Novo item no Monday Contratos

Logs:

```bash
gcloud run services logs read contratos-webhook --region=southamerica-east1 --project=PROJECT_ID
```

## Variáveis de ambiente

O container usa `PORT=8080` (padrão Cloud Run). Secrets são injetados via `--set-secrets` no `cloudbuild-contratos.yaml`.
