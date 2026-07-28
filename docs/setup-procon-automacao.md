# Automação Procon (produção)

Checklist para o workflow **Procon automation (every 30 min)** rodar sem intervenção manual.

## O que roda sozinho

Workflow **Procon automation (every 30 min)** (arquivo `.github/workflows/procon-hourly.yml`):

| Agenda (UTC) | Agenda (Brasília, UTC−3) | Etapas |
|--------------|---------------------------|--------|
| `:00`, `:15`, `:30`, `:45` | mesmos minutos (−3h na hora) | `process` — Gmail → Monday |
| `:00` | `:00` (−3h) | `elaborate` — respostas (Gemini/OpenAI) |

Guia sem terminal: [`docs/procon-guia-simples.md`](procon-guia-simples.md)

| Comando | Fontes (`--sources`) no `process` |
|---------|-------------------------------------|
| `procon-email process` | `sp`, `sc`, `alerj`, `campinas`, `uberlandia` |
| `procon-email elaborate` | Casos Monday com Docs SAC (só na run do `:00` UTC) |

Workflow **Proconsumidor local processing** (runner **self-hosted** — portal bloqueia datacenter):

| Etapa | Fontes |
|-------|--------|
| `process` | `proconsumidor` (e-mail + portal MJ) |

### Cobertura por origem

| Origem | `source_id` | Automático em Actions |
|--------|-------------|------------------------|
| Procon-SP CIP | `sp` | Sim (a cada 30 min) |
| Procon-SP Processo Administrativo | `sp` (PA) | Sim (a cada 30 min) |
| Proconsumidor (MJ) | `proconsumidor` | Sim, com runner self-hosted |
| Campinas | `campinas` | Sim (a cada 30 min) |
| SC / SSP (e-mail + PDF) | `sc` | Sim (a cada 30 min) |
| ALERJ (RJ) | `alerj` | Sim (a cada 30 min) |
| Uberlândia | `uberlandia` | Sim (a cada 30 min) |

Credenciais de portal (quando necessário): board Monday **Acessos** (`credentials` no código).

Local Proconsumidor: `bash scripts/run-proconsumidor-process.sh` (Mac/PC no Brasil).

## SLA (e-mail → Monday)

O cadastro no Monday ocorre no passo `process` do workflow **Procon automation (every 30 min)**. O e-mail de aviso ao SAC (“novo caso no Monday”) é automação do próprio Monday, disparada **quando o item é criado** — não é enviado pelo repositório.

### Por que pode demorar horas (ex.: Camila — e-mail 27/07 22:51, Monday ~28/07 04:49)

1. **Agenda do GitHub Actions** — o cron roda em **UTC** e o GitHub **não garante** execução em todo `:00`; é comum pular várias horas em repositórios privados/inativos. No dia 28/07/2026, entre **21:49 UTC (27/07)** e **07:47 UTC (28/07)** não houve execução agendada; o CIP chegou às **01:51 UTC** nesse intervalo e só foi processado na run das **07:47 UTC** (~**04:47** em São Paulo).
2. **Fila na hora cheia** — antes só havia um disparo por hora (`:00` UTC); agora há também `:30` UTC.
3. **Falha no `process`** — portal Playwright, Monday ou Drive: o e-mail permanece **não lido** até uma run seguinte ter sucesso.

### Mitigações no repositório

- **Checagem a cada 30 minutos** (`:00` e `:30` UTC) — só `process`; elaboração 1×/hora no `:00` UTC.
- `process` roda **antes** da validação Gemini (Monday não depende da API de elaboração).
- `concurrency` sem cancelar run em andamento.

### Disparo manual

```bash
gh workflow run "Procon automation (every 30 min)"
# Só cadastrar casos, sem elaborar:
gh workflow run "Procon automation (every 30 min)" -f skip_elaborate=true
```

### Ping externo (Cloud Scheduler) — recomendado em produção

Quando o GitHub **não dispara** o cron por várias horas, use o **Cloud Scheduler** para chamar `workflow_dispatch` na API do GitHub.

Guia completo: [`docs/gcp-procon-github-scheduler.md`](gcp-procon-github-scheduler.md)

```bash
export GITHUB_ACTIONS_PAT="github_pat_..."   # Actions: Read and write no repo
export PROJECT_ID="b4a-prj-SEU-SLUG-stg"
bash scripts/setup-gcp-github-procon-scheduler.sh
```

Cria checagem **a cada 30 min** (só `process` / Monday) + backup de **elaborate** no minuto **:15** de cada hora (horário de Brasília).

## Secrets no GitHub (Settings → Secrets and variables → Actions)

| Secret | Obrigatório | Uso |
|--------|-------------|-----|
| `GMAIL_OAUTH_JSON` | Sim | OAuth Google |
| `GMAIL_TOKEN_JSON` | Sim | Token Gmail + Drive |
| `MONDAY_API_TOKEN` | Sim | Board de reclamações |
| `GEMINI_API_KEY` | Sim* | Elaboração (chave com **billing** no Google AI Studio) |
| `OPENAI_API_KEY` | Recomendado | Fallback quando Gemini retorna 429/cota |
| `GEMINI_MODEL` | Opcional | Ex.: `gemini-2.5-flash` |

\*Sem `OPENAI_API_KEY`, o fluxo depende só do Gemini; picos de cota podem atrasar respostas até a próxima hora.

### Como criar `OPENAI_API_KEY` (API paga — não é assinatura do app ChatGPT)

1. Acesse https://platform.openai.com/api-keys  
2. Crie uma chave e ative billing em https://platform.openai.com/account/billing  
3. No GitHub: **New repository secret** → nome `OPENAI_API_KEY` → cole a chave  
4. (Opcional) No Cursor Cloud Agents → Secrets → mesmo nome, para testes do agente

### Gemini com billing

1. https://aistudio.google.com/apikey  
2. Use projeto com faturamento habilitado (evita teto agressivo do tier gratuito)  
3. Confirme que `GEMINI_API_KEY` no GitHub é dessa chave

## Monday (recomendado)

No board de reclamações, colunas **link** com títulos reconhecidos pelo sistema:

- **Docs SAC** — pasta do consumidor no Drive  
- **Resposta completa** / **Resumo resposta** / **PDF unificado** — preenchidas após `elaborate`

Sem essas colunas, os arquivos ainda vão para o Drive; só os links no Monday podem ficar vazios.

## Drive (por caso)

- Raiz: PDF `Atendimento Procon...` + pasta `Informações` com **.txt** do SAC  
- Saída: `Resposta Automatica` → `resposta-completa.txt`, `resposta-resumo-1024.txt`, `resposta-unificada.pdf`

## Disparar manualmente

```bash
gh workflow run "Procon automation (every 30 min)"
gh run list --workflow="Procon automation (every 30 min)" --limit 3
```

## Validar após configurar secrets

Aguarde um run verde em Actions. Caso com Docs SAC + TXT deve ganhar `Resposta Automatica` na próxima execução (ou na mesma, se estiver na fila).
