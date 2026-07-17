# ClassificacaoProcons

Agente de automação da B4A para dois fluxos jurídicos/administrativos:

1. **Procon-SP** — triagem, cadastro e elaboração de resposta de reclamações (CIP).
2. **Contratos** — automação de contratos assinados no Autentique, com cadastro/atualização no Monday e arquivamento no Google Drive.

Ambos os fluxos compartilham o mesmo pacote Python (`classificacao_procons`), as mesmas credenciais Google e integração com Monday.com e Gemini.

## Subsistemas

### 1. Procon-SP (e-mail → portal → Drive → Monday → resposta)

Monitora a caixa de entrada do Gmail em busca de notificações de CIP do Procon-SP e, para cada e-mail **não lido**:

1. Lê o e-mail e extrai a **URL do portal** (`fornecedor2.procon.sp.gov.br`) e o **código de acesso**.
2. Acessa o portal, faz login com o código e baixa o PDF da reclamação.
3. Cria uma pasta no Google Drive (nome da consumidora) e salva o PDF.
4. Cadastra o caso no Monday.com (grupo "pendentes de resposta").
5. Marca o e-mail como lido.
6. (Etapa `elaborate`) Elabora a resposta com Gemini, gera o PDF de resposta e unifica anexos SAC.

**Critérios de identificação do e-mail:**

| Campo | Valor |
|-------|-------|
| Remetente | `procon.naoresponder@procon.sp.gov.br` |
| Assunto | `Fundação Procon-SP - Notificação de emissão de CIP` |

### 2. Contratos (Autentique → Monday → Drive)

Serviço HTTP (Cloud Run) que escuta webhooks do Autentique e do Monday:

| Evento (Autentique) | Ação |
|---------------------|------|
| `document.created` | Cria item no Monday **Controle Assinaturas** (grupo Jan/Luciano) |
| `signature.accepted` | Atualiza status e move entre grupos quando alguém assina |
| `document.finished` | Baixa o PDF assinado, extrai dados com Gemini, salva no Drive e atualiza o Monday |

Também expõe um webhook do Monday (`serve-monday`) que enriquece itens criados no quadro **Contratos**.

## Pré-requisitos

- Python 3.11+ (o container usa 3.12)
- Projeto no [Google Cloud Console](https://console.cloud.google.com/) com **Gmail API** e **Drive API** habilitadas
- Credenciais OAuth 2.0 (tipo "Desktop app") salvas em `credentials/gmail-oauth.json`
- Para o portal Procon: navegador do Playwright (`playwright install chromium`)
- Opcional: token do Monday.com e chave da API Gemini (ver [Variáveis de ambiente](#variáveis-de-ambiente))

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

## Configuração do Gmail

1. Crie credenciais OAuth no Google Cloud Console (Gmail + Drive habilitados).
2. Baixe o JSON e salve como `credentials/gmail-oauth.json` (**nunca commitar**).
3. Na primeira execução, o fluxo OAuth abrirá o navegador e salvará o token em `credentials/gmail-token.json`.

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `GMAIL_CREDENTIALS_PATH` | `credentials/gmail-oauth.json` | Client secrets OAuth |
| `GMAIL_TOKEN_PATH` | `credentials/gmail-token.json` | Token autorizado (Gmail + Drive) |
| `MONDAY_API_TOKEN` | — | Token da API do Monday.com |
| `MONDAY_BOARD_NAME` | `procons` | Nome do quadro Procon |
| `MONDAY_BOARD_ID` | — | ID do quadro (opcional, evita busca por nome) |
| `MONDAY_ORIGIN_LABEL` | `Glam "Clube"` | Rótulo de origem no Monday |
| `GEMINI_API_KEY` | — | Chave da API Gemini (elaboração de resposta / extração de contratos) |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Modelo Gemini preferido (com fallback automático) |
| `AUTENTIQUE_API_TOKEN` | — | Token da API do Autentique (contratos) |
| `AUTENTIQUE_WEBHOOK_SECRET` | — | Segredo para validar assinatura dos webhooks do Autentique |

Em ambientes containerizados, os JSON de credenciais podem ser injetados via `GMAIL_OAUTH_JSON` e `GMAIL_TOKEN_JSON` (o entrypoint grava os arquivos automaticamente).

## Uso — CLI `procon-email`

```bash
procon-email auth                 # conectar Google (Gmail + Drive)
procon-email list                 # listar e-mails não lidos (JSON)
procon-email process              # fluxo automático: portal + Drive + Monday
procon-email process --dry-run    # simular sem executar
procon-email elaborate            # elaborar respostas (requer GEMINI_API_KEY)
procon-email register-monday --access-code "..."  # cadastrar caso já salvo no Drive
```

Comandos auxiliares:

```bash
procon-portal --code "..."                                   # só o portal
procon-drive --consumer-name "..." --pdf downloads/arquivo.pdf  # só o Drive
```

Saída de `list` (JSON):

```json
[
  {
    "message_id": "abc123",
    "subject": "Fundação Procon-SP - Notificação de emissão de CIP",
    "sender": "procon.naoresponder@procon.sp.gov.br",
    "received_at": "2025-07-14T10:00:00+00:00",
    "portal_url": "https://fornecedor2.procon.sp.gov.br/login",
    "access_code": "ABC123-XYZ789"
  }
]
```

### Agendamento automático (a cada 1 hora)

**Neste ambiente (tmux):**

```bash
bash scripts/start-scheduler.sh
```

Roda o processamento a cada 1 hora. Logs em `logs/pipeline.log` e `logs/scheduler.log`.
Para parar: `tmux -f /exec-daemon/tmux.portal.conf kill-session -t procon-scheduler`.

**Em servidor com cron:**

```bash
bash scripts/install-cron.sh
```

Em produção, o agendamento roda no GitHub Actions (ver [Workflows](#github-actions)).

## Uso — CLI `contratos-webhook`

```bash
contratos-webhook serve                       # webhook Autentique (HTTP, porta 8080)
contratos-webhook serve-monday                # webhook Monday (quadro Contratos)
contratos-webhook process --document-id ID    # processa um documento assinado por ID
contratos-webhook sync-controle               # sincroniza Controle Assinaturas com o Autentique
contratos-webhook sync-controle --dry-run     # simular
contratos-webhook register-controle --document-id ID  # cria item no Controle Assinaturas
```

Flags úteis: `--dry-run`, `--skip-gemini`, `--host`, `--port`.

## Uso programático (parser)

Para testar o parser com o corpo de um e-mail, sem Gmail:

```python
from classificacao_procons.email import parse_procon_notification_body

result = parse_procon_notification_body(html=email_html)
print(result.portal_url, result.access_code)
```

## Estrutura do projeto

```
src/classificacao_procons/
├── cli.py                # CLI procon-email
├── portal_cli.py         # CLI procon-portal
├── drive_cli.py          # CLI procon-drive
├── pipeline.py           # fluxo Procon: e-mail → portal → Drive → Monday
├── response_pipeline.py  # elaboração de resposta (Gemini + PDF)
├── email/                # parser e cliente Gmail
├── portal/               # automação do portal Procon (Playwright)
├── drive/                # cliente Drive, leitura e geração de PDF
├── monday/               # cliente e mapeamento Monday.com
├── gemini/               # cliente Gemini
└── contratos/            # subsistema de contratos (Autentique + Monday + Drive)
    ├── webhook_cli.py    # CLI contratos-webhook
    ├── pipeline.py       # processamento de documento assinado
    ├── autentique/       # cliente e webhook do Autentique
    └── ...
scripts/    # schedulers, deploy e utilitários
docs/       # guias de deploy e operação
tests/      # testes unitários
```

## GitHub Actions

| Workflow | Gatilho | Função |
|----------|---------|--------|
| `procon-hourly.yml` | agendado (1h) + manual | Processa e elabora respostas do Procon |
| `setup-google-token.yml` | manual | Gera link OAuth e grava o token do Google |
| `contratos-process-test.yml` | manual | Testa o processamento de um contrato assinado |
| `contratos-register-controle.yml` | manual | Registra um contrato no Controle Assinaturas |
| `contratos-sync-controle.yml` | manual | Sincroniza o Controle Assinaturas com o Autentique |
| `discover-drive-contratos.yml` | manual | Descobre a árvore de pastas de Contratos no Drive |

## Deploy (GCP)

- **Worker Procon** (Cloud Run Job): `cloudbuild.yaml` → job `classificacao-procons-worker`.
- **Webhook de contratos** (Cloud Run Service): `cloudbuild-contratos.yaml` → serviço `contratos-webhook`.

```bash
gcloud builds submit --config=cloudbuild.yaml --project=PROJECT_ID
gcloud builds submit --config=cloudbuild-contratos.yaml --project=PROJECT_ID
```

Secrets são injetados via Secret Manager (`--set-secrets`). Guias detalhados:

- [`docs/deploy-contratos-webhook.md`](docs/deploy-contratos-webhook.md) — publicar o webhook de contratos
- [`docs/deploy-24h.md`](docs/deploy-24h.md) e [`docs/ativar-24h-simples.md`](docs/ativar-24h-simples.md) — operação 24h
- [`docs/modo-manual-sem-cloud-run.md`](docs/modo-manual-sem-cloud-run.md) — modo manual sem Cloud Run

## Validação

```bash
pip install -e ".[dev]"
ruff check src tests
pytest
```

## Segurança

- **Nunca** commitar `credentials/` nem qualquer JSON de token/segredo.
- Em produção, todos os segredos ficam no **Secret Manager** (nunca em código, commits ou chat).

## Próximas etapas

- [x] Portal Procon: login + código → extrair dados e PDF
- [x] Google Drive: criar pasta e upload do PDF
- [x] Monday.com: cadastro em "pendentes de resposta"
- [x] Elaboração de resposta com Gemini (requer `GEMINI_API_KEY`)
- [x] PDF da resposta + unificação de anexos SAC (`resposta-unificada.pdf` no Drive)
- [x] Persistência de estado no GitHub Actions (evita reprocessar o mesmo caso)
- [x] Contratos: webhook Autentique → Monday + Drive
- [ ] Envio automático da resposta no portal Procon

## Metadados B4A

- **Product:** _pendente definição no registry B4A._
- **Owner:** _pendente._
- **Environments:** `b4a-prj-{slug}-stg` / `-prd` (validar em staging antes de produção).
