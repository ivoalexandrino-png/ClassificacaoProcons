# Automação Procon (produção)

Checklist para o job **Procon hourly processing** rodar sem intervenção manual.

## O que roda sozinho (a cada hora)

Workflow **Procon hourly processing** (`main`):

| Etapa | Comando | Fontes (`--sources`) |
|-------|---------|----------------------|
| `process` | `procon-email process` | `sp`, `sc`, `alerj`, `campinas`, `uberlandia` |
| `elaborate` | `procon-email elaborate` | Todos os casos Monday com Docs SAC |

Workflow **Proconsumidor local processing** (runner **self-hosted** — portal bloqueia datacenter):

| Etapa | Fontes |
|-------|--------|
| `process` | `proconsumidor` (e-mail + portal MJ) |

### Cobertura por origem

| Origem | `source_id` | Automático em Actions |
|--------|-------------|------------------------|
| Procon-SP CIP | `sp` | Sim (hourly) |
| Procon-SP Processo Administrativo | `sp` (PA) | **Pendente** — merge PR #51 |
| Proconsumidor (MJ) | `proconsumidor` | Sim, com runner self-hosted |
| Campinas | `campinas` | Sim (hourly) |
| SC / SSP (e-mail + PDF) | `sc` | Sim (hourly) |
| ALERJ (RJ) | `alerj` | Sim (hourly) |
| Uberlândia | `uberlandia` | Sim (hourly) |

Credenciais de portal (quando necessário): board Monday **Acessos** (`credentials` no código).

Local Proconsumidor: `bash scripts/run-proconsumidor-process.sh` (Mac/PC no Brasil).

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
gh workflow run "Procon hourly processing"
gh run list --workflow="Procon hourly processing" --limit 3
```

## Validar após configurar secrets

Aguarde um run verde em Actions. Caso com Docs SAC + TXT deve ganhar `Resposta Automatica` na próxima execução (ou na mesma, se estiver na fila).
