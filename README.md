# ClassificacaoProcons

Worker Python para automação jurídica B4A: triagem de CIPs do Procon-SP e processamento de contratos assinados (Autentique → Drive → Monday).

## Product

_Pendente definição no registry B4A._

## Owner

Ivo Alexandrino (`ivo.alexandrino@b4a.com.br`)

## Environments

| Ambiente | Uso atual |
|----------|-----------|
| GitHub Actions | Pipeline Procon horário (`procon-hourly.yml`) |
| GCP (`sonic-cat-479513-b2`, `southamerica-east1`) | Cloud Run Job (Procon) e webhook de contratos (quando deployado) |

Staging/produção B4A (`b4a-prj-{slug}-stg` / `-prd`) — a definir após slug no registry.

## O que o repositório faz

### 1. Procon (CIP)

Monitora e-mails de notificação do Procon-SP e executa o fluxo:

```
Gmail (CIP) → portal Procon (PDF) → Google Drive → Monday.com
                                              ↓
                         Gemini elabora resposta + PDF unificado no Drive
```

| Etapa | Comportamento |
|-------|---------------|
| E-mail | Remetente `procon.naoresponder@procon.sp.gov.br`, assunto de emissão de CIP |
| Portal | Login com código de acesso; baixa dados e PDF da reclamação |
| Drive | Pasta por consumidora; upload do PDF da CIP |
| Monday | Cadastro em board de pendentes (origem, prazos SAC/jurídico, causa) |
| Resposta | Casos com Docs SAC → Gemini → `resposta-unificada.pdf` no Drive |

**Ainda não automatizado:** envio da resposta no portal Procon.

### 2. Contratos (Autentique)

Webhook HTTP que reage a eventos do Autentique:

| Evento | Ação |
|--------|------|
| `document.created` | Cria item no Monday **Controle Assinaturas** |
| `signature.accepted` | Atualiza status e move entre grupos |
| `document.finished` | Baixa PDF assinado, extrai dados (Gemini), salva no Drive e atualiza Monday |

Detalhes de deploy: [`docs/deploy-contratos-webhook.md`](docs/deploy-contratos-webhook.md).

## Estrutura

```
src/classificacao_procons/
  email/          # parser + cliente Gmail
  portal/         # Playwright no portal Procon
  drive/          # upload/leitura Drive + PDF builder
  monday/         # cadastro e consulta de casos
  gemini/         # elaboração de resposta / extração
  contratos/      # webhook Autentique + sync Monday/Drive
  cli.py          # procon-email
  portal_cli.py   # procon-portal
  drive_cli.py    # procon-drive
docs/             # guias de deploy e operação 24h
.github/workflows/
  procon-hourly.yml
  setup-google-token.yml
  contratos-*.yml
```

## Pré-requisitos

- Python 3.11+
- Projeto Google Cloud com **Gmail API** e **Google Drive API**
- Credenciais OAuth 2.0 (Desktop app) em `credentials/gmail-oauth.json` (nunca commitar)
- Playwright (Chromium) para o portal Procon
- Tokens/secrets externos conforme o fluxo (Monday, Gemini, Autentique)

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

## Configuração

### Google (Gmail + Drive)

```bash
procon-email auth
```

Na primeira execução o OAuth abre o navegador e grava `credentials/gmail-token.json`.

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `GMAIL_CREDENTIALS_PATH` | `credentials/gmail-oauth.json` | Client secrets OAuth |
| `GMAIL_TOKEN_PATH` | `credentials/gmail-token.json` | Token autorizado |

Setup sem pasta local (GitHub): [`docs/ativar-24h-simples.md`](docs/ativar-24h-simples.md).

### Integrações

| Variável | Obrigatória para | Descrição |
|----------|------------------|-----------|
| `MONDAY_API_TOKEN` | Procon + Contratos | API token Monday.com |
| `MONDAY_BOARD_NAME` / `MONDAY_BOARD_ID` | Procon (opcional) | Board de reclamações |
| `GEMINI_API_KEY` | Elaboração / contratos | Chave Gemini |
| `GEMINI_MODEL` | Opcional | Override do modelo (padrão `gemini-3.5-flash`) |
| `AUTENTIQUE_WEBHOOK_SECRET` | Webhook contratos | Validação de assinatura |

Em produção, secrets ficam no **Secret Manager** / GitHub Secrets — nunca no repositório.

## Uso — Procon

### Fluxo completo (e-mails não lidos)

```bash
procon-email process
procon-email process --dry-run
```

Para cada CIP não lida: extrai código → portal → PDF no Drive → Monday → marca e-mail como lido.

### Elaborar respostas (casos com Docs SAC)

```bash
procon-email elaborate
procon-email elaborate --dry-run
```

### Outros comandos

```bash
procon-email auth
procon-email list
procon-email register-monday --access-code "CODIGO"
procon-portal --code "CODIGO"
procon-drive --consumer-name "..." --cip "..." --pdf downloads/arquivo.pdf
```

### Parser sem Gmail

```python
from classificacao_procons.email import parse_procon_notification_body

result = parse_procon_notification_body(html=email_html)
print(result.portal_url, result.access_code)
```

## Uso — Contratos

```bash
contratos-webhook serve --port 8080
contratos-webhook process --document-id "DOC_ID"
contratos-webhook sync-controle
contratos-webhook register-controle --document-id "DOC_ID"
```

## Automação 24h

| Caminho | Como |
|---------|------|
| **GitHub Actions (recomendado hoje)** | Workflow horário — [`docs/ativar-24h-simples.md`](docs/ativar-24h-simples.md) |
| Cloud Run Job + Scheduler | [`docs/deploy-24h.md`](docs/deploy-24h.md) |
| Local / cron | `bash scripts/start-scheduler.sh` ou `bash scripts/install-cron.sh` |
| Sem Cloud Run | [`docs/modo-manual-sem-cloud-run.md`](docs/modo-manual-sem-cloud-run.md) |

O workflow `procon-hourly` roda a cada hora: `process` → `elaborate`, com cache de estado em `data/` para não reprocessar o mesmo protocolo/caso.

## Validação

```bash
pip install -e ".[dev]"
ruff check src tests
pytest
```

## Segredos

Nunca commitar `credentials/`, tokens, nem arquivos `*.json` de OAuth. Usar Secret Manager (GCP) ou GitHub Secrets.
