# ClassificacaoProcons

Agente de triagem e cadastro de reclamações do Procon-SP, com automação adicional de contratos assinados (Autentique).

## O que o repositório faz

### 1. Pipeline Procon (e-mail → portal → Drive → Monday → resposta)

Monitora a caixa de entrada do Gmail em busca de notificações de CIP do Procon-SP e, para cada e-mail não lido:

1. Extrai a **URL do portal** (`fornecedor2.procon.sp.gov.br`) e o **código de acesso**
2. Acessa o portal (Playwright) e baixa o PDF da reclamação
3. Cria pasta no Google Drive (nome da consumidora) e salva o PDF
4. Cadastra o caso no Monday ("pendentes de resposta"), com origem, prazos e notificação
5. Marca o e-mail como lido

Depois, o comando `elaborate` gera a resposta com Gemini a partir dos Docs SAC e salva `resposta-unificada.pdf` no Drive.

Critérios de identificação do e-mail:

| Campo | Valor |
|-------|-------|
| Remetente | `procon.naoresponder@procon.sp.gov.br` |
| Assunto | `Fundação Procon-SP - Notificação de emissão de CIP` |

### 2. Agente Jurídico (intimações → andamento → Monday)

Agente para o jurídico interno: lê intimações/pushes por e-mail, identifica o
processo (nº CNJ, tribunal, vara), o tipo de movimento e extrai prazos e
audiências. Quando há **providência**, registra no Monday para controlar prazos e
audiências. Foi desenhado para, no futuro, acionar dois agentes ainda inexistentes
(elaboração/protocolo de peças e atualização de relatórios contingenciais) via
interfaces plugáveis.

```bash
procon-juridico parse --file intimacao.txt   # extrair processo + providência (offline)
procon-juridico list                         # intimações não lidas (JSON)
procon-juridico process                      # providência + Monday
procon-juridico process --dry-run            # simular
```

Detalhes, board do Monday, variáveis de ambiente, regras de prazo (CPC dias úteis)
e pontos de extensão dos agentes futuros: [`docs/agente-juridico.md`](docs/agente-juridico.md).

### 3. Pipeline Contratos (Autentique → Monday → Drive)

Servidor de webhooks (`contratos-webhook`) que reage a eventos do Autentique e do Monday:

| Evento | O que faz |
|--------|-----------|
| `document.created` (Autentique) | Cria item no Monday **Controle Assinaturas** |
| `signature.accepted` (Autentique) | Atualiza status e move entre grupos quando alguém assina |
| `document.finished` (Autentique) | Baixa o PDF assinado, extrai dados com Gemini, salva no Drive e atualiza Monday |
| Item criado no quadro Contratos (Monday) | Enriquece o item com dados extraídos por Gemini |

## Pré-requisitos

- Python 3.11+
- Projeto no [Google Cloud Console](https://console.cloud.google.com/) com **Gmail API** e **Drive API** habilitadas
- Credenciais OAuth 2.0 (tipo "Desktop app") salvas em `credentials/gmail-oauth.json`

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuração

### Google (Gmail + Drive)

1. Crie credenciais OAuth no Google Cloud Console.
2. Baixe o JSON e salve como `credentials/gmail-oauth.json` (não commitar).
3. Rode `procon-email auth` e siga as instruções; o token fica em `credentials/gmail-token.json`.

### Variáveis de ambiente

| Variável | Obrigatória para | Descrição |
|----------|------------------|-----------|
| `GMAIL_CREDENTIALS_PATH` | — (padrão `credentials/gmail-oauth.json`) | Client secrets OAuth |
| `GMAIL_TOKEN_PATH` | — (padrão `credentials/gmail-token.json`) | Token autorizado |
| `MONDAY_API_TOKEN` | Cadastro/atualização no Monday | Token da API do Monday |
| `GEMINI_API_KEY` | `elaborate` e extração de contratos | Chave da API do Gemini |
| `AUTENTIQUE_API_TOKEN` | Pipeline de contratos | Token da API do Autentique |
| `AUTENTIQUE_WEBHOOK_SECRET` | Webhook de contratos (recomendado) | Valida assinatura dos webhooks |

Em produção, todos os segredos ficam no Secret Manager (ver `cloudbuild*.yaml`).

## Uso — pipeline Procon

```bash
procon-email auth                          # conectar Gmail + Drive
procon-email process                       # e-mails novos: portal + Drive + Monday
procon-email process --dry-run             # simular sem executar
procon-email elaborate                     # gerar respostas (Gemini) para casos com Docs SAC
procon-email register-monday --access-code "..."  # cadastrar no Monday um caso já salvo no Drive
procon-email list                          # listar e-mails não lidos (JSON)
```

Comandos auxiliares:

```bash
procon-portal --code "..."                 # só portal (download do PDF)
procon-drive --consumer-name "..." --pdf downloads/arquivo.pdf
```

### Agendamento (a cada 1 hora)

- **GitHub Actions:** workflow `procon-hourly.yml` (estado persistido para evitar reprocessar).
- **Cloud Run Job + Cloud Scheduler:** ver `docs/deploy-24h.md` e `cloudbuild.yaml`.
- **Neste ambiente de desenvolvimento:** `bash scripts/start-scheduler.sh` (logs em `logs/`); parar com `tmux -f /exec-daemon/tmux.portal.conf kill-session -t procon-scheduler`.
- **Servidor com cron:** `bash scripts/install-cron.sh`.

## Uso — pipeline Contratos

```bash
contratos-webhook serve                      # servidor HTTP p/ webhooks do Autentique (porta 8080)
contratos-webhook serve-monday               # servidor HTTP p/ webhooks do Monday (quadro Contratos)
contratos-webhook process --document-id "..."   # processar um documento assinado manualmente
contratos-webhook sync-controle --dry-run    # sincronizar Controle Assinaturas a partir do Autentique
contratos-webhook register-controle --document-id "..."  # registrar um documento no Controle
```

Sem Cloud Run, os workflows do GitHub Actions cobrem o fluxo manualmente (`contratos-sync-controle.yml`, `contratos-register-controle.yml`, `contratos-process-test.yml`) — ver `docs/modo-manual-sem-cloud-run.md`.

## Deploy

| Alvo | Arquivo | Descrição |
|------|---------|-----------|
| Cloud Run Job (Procon horário) | `cloudbuild.yaml` | Job `classificacao-procons-worker` disparado pelo Cloud Scheduler |
| Cloud Run Service (webhook contratos) | `cloudbuild-contratos.yaml` | Serviço `contratos-webhook` (porta 8080) |

Guias em `docs/`: `deploy-24h.md`, `deploy-contratos-webhook.md`, `ativar-24h-simples.md`, `modo-manual-sem-cloud-run.md`.

## Estrutura

```
src/classificacao_procons/
├── email/       # parser e cliente Gmail
├── portal/      # portal Procon (Playwright)
├── drive/       # Google Drive: upload, leitura, geração de PDF
├── monday/      # cliente e mapeamento Monday
├── gemini/      # cliente Gemini
├── juridico/    # agente jurídico (intimações → andamento → Monday)
├── contratos/   # Autentique, webhooks, sync Controle Assinaturas
├── cli.py       # CLI procon-email
├── pipeline.py  # pipeline principal (e-mail → portal → Drive → Monday)
└── response_pipeline.py  # elaboração de respostas
```

## Uso programático (parser)

Para testar o parser com o corpo de um e-mail, sem Gmail:

```python
from classificacao_procons.email import parse_procon_notification_body

result = parse_procon_notification_body(html=email_html)
print(result.portal_url, result.access_code)
```

## Próximas etapas

- [x] Portal Procon: login + código → extrair dados e PDF
- [x] Google Drive: criar pasta e upload do PDF
- [x] Monday.com: cadastro em "pendentes de resposta"
- [x] Elaboração de resposta com Gemini (requer `GEMINI_API_KEY`)
- [x] PDF da resposta + unificação de anexos SAC (`resposta-unificada.pdf` no Drive)
- [x] Persistência de estado no GitHub Actions (evita reprocessar o mesmo caso)
- [x] Contratos: webhooks Autentique + Monday, sync Controle Assinaturas
- [ ] Envio automático no portal Procon

## Validação

```bash
ruff check src tests
pytest
```

## Product

_Pendente definição no registry B4A._

## Owner

_Pendente._

## Environments

_Pendente (stg/prd)._
