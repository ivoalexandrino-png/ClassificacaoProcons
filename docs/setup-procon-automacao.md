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
| `procon-email process-interactions` | Interação do consumidor (Procon-SP) → update no Monday |
| `procon-email elaborate` | Casos Monday com Docs SAC (só na run do `:00` UTC) |

Workflow **Proconsumidor local processing** (`.github/workflows/procon-proconsumidor-local.yml`, runner **self-hosted** — portal bloqueia datacenter):

| Agenda (UTC) | Etapa |
|--------------|--------|
| `:05`, `:20`, `:35`, `:50` | `process` — fonte `proconsumidor` (**cron pausado** até runner `procon-br`; use **Run workflow** ou reative o `schedule` no YAML) |

Estado em `data/` é o **mesmo** do workflow hourly (cache `procon-pipeline-state-*`). Os dois workflows usam `concurrency: procon-pipeline-mutex` para não rodar `process` ao mesmo tempo e sobrescrever estado.

**Runner self-hosted (obrigatório para o cron do Proconsumidor):**

1. Máquina no Brasil (IP que não receba 403 em `https://proconsumidor.mj.gov.br/`).
2. GitHub → **Settings → Actions → Runners → New self-hosted runner** (Linux ou macOS).
3. Instalar o runner: `bash scripts/setup-github-proconsumidor-runner.sh` (label **`procon-br`**). Guia: [`docs/procon-proconsumidor-runner.md`](procon-proconsumidor-runner.md).
4. Mesmos secrets do hourly (`GMAIL_*`, `MONDAY_API_TOKEN`) no repositório — o runner herda secrets do repo.
5. Validar: `gh workflow run "Proconsumidor local processing"` e conferir job verde (ou warning 403 se o IP ainda for bloqueado).

Sem runner online, jobs agendados ficam em fila; o hourly **não** inclui `proconsumidor` e continua igual.

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
- Mutex `procon-hourly-automation` no hourly; Proconsumidor usa grupo próprio (cron só após runner `procon-br`).

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

### Watchdog de SLA (recomendado)

Workflow **Procon SLA watchdog** (`.github/workflows/procon-sla-watchdog.yml`):

| O que faz | Detalhe |
|-----------|---------|
| Agenda | `:05` e `:35` UTC (entre os crons do hourly) |
| Gmail | Falha se houver CIP/reclamação **não lida** há mais de **90 min** (padrão) |
| GitHub | Falha se **Procon automation** não tiver run **verde** há mais de **150 min** |
| Correção | Dispara `Procon automation` com `skip_elaborate=true` (exige secret **`PROCON_ACTIONS_PAT`** no repo) |

Local:

```bash
procon-email sla-check --max-age-minutes 90 --max-workflow-age-minutes 150
```

No GitHub → **Settings → Secrets → Actions**, crie **`PROCON_ACTIONS_PAT`** (fine-grained PAT com **Actions: Read and write** neste repositório). O nome não pode começar com `GITHUB_`. No Cursor Cloud Agents, o mesmo token pode ficar como `GITHUB_ACTIONS_PAT` no start hook. Ver [`docs/cloud-agent-autonomia.md`](cloud-agent-autonomia.md).

## Secrets no GitHub (Settings → Secrets and variables → Actions)

| Secret | Obrigatório | Uso |
|--------|-------------|-----|
| `GMAIL_OAUTH_JSON` | Sim | OAuth Google |
| `GMAIL_TOKEN_JSON` | Sim | Token Gmail + Drive |
| `MONDAY_API_TOKEN` | Sim | Board de reclamações |
| `GEMINI_API_KEY` | Sim* | Elaboração (chave com **billing** no Google AI Studio) |
| `OPENAI_API_KEY` | Recomendado | Fallback quando Gemini retorna 429/cota |
| `GEMINI_MODEL` | Opcional | Ex.: `gemini-2.5-flash` |
| `PROCON_ACTIONS_PAT` | Recomendado | Watchdog SLA + ping Cloud Scheduler + dispatch manual (no repo; não use prefixo `GITHUB_`) |

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

- Raiz: PDF da reclamação + pasta `Informações` com anexos do SAC (**.txt**, **PDF**, imagens na resposta unificada)  
- PDF **digitalizado** (sem camada de texto) e imagens: texto extraído via **Gemini** antes da elaboração  
- A elaboração **prioriza o relato do SAC** na pasta `Informações`; a resposta não pode contradizer o posicionamento do SAC (ex.: negar brinde se o SAC negou)  
- Saída: `Resposta Automatica` → `resposta-completa.txt`, `resposta-resumo-1024.txt`, `resposta-unificada.pdf` (resposta + anexos SAC; **sem** o PDF da CIP do Procon)

## Disparar manualmente

```bash
gh workflow run "Procon automation (every 30 min)"
gh workflow run "Proconsumidor local processing"
gh run list --workflow="Procon automation (every 30 min)" --limit 3
```

## Validar após configurar secrets

Aguarde um run verde em Actions. Caso com **Docs SAC** e arquivos em `Informações` deve ganhar `Resposta Automatica` na próxima execução (ou na mesma, se estiver na fila).
