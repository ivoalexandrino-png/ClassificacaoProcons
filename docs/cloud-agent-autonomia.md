# Autonomia do Cloud Agent (contratos + GitHub Actions)

Guia para o agente rodar **sozinho** sincronizações e workflows, sem depender do GCP/Cloud Run.

## O que o agente consegue fazer (com setup completo)

| Tarefa | Comando local | Workflow GitHub |
|--------|---------------|-----------------|
| Sincronizar Controle Assinaturas | `contratos-webhook sync-controle` | **Sync Controle Assinaturas** |
| Processar 1 contrato assinado | `contratos-webhook process --document-id ...` | **Test contrato assinado** |
| **Tudo de uma vez** (recomendado) | `contratos-webhook sync-all` | **Catch-up contratos** |
| Deploy GCP (quando TI liberar) | — | **Bootstrap contratos GCP** |

## Secrets obrigatórios no Cursor (Cloud Agents → Secrets)

Cadastre em https://cursor.com/dashboard (aba **Secrets**):

| Nome do secret | Onde obter | Para quê |
|----------------|------------|----------|
| `MONDAY_API_TOKEN` | Monday → API | Monday Controle + Contratos |
| `AUTENTIQUE_API_TOKEN` | Autentique → API | Listar/processar documentos |
| `GEMINI_API_KEY` | Google AI Studio | Classificar contratos assinados |
| `GMAIL_OAUTH_JSON` | JSON OAuth Google | Upload no Drive |
| `GMAIL_TOKEN_JSON` | `gmail-token.json` | Upload no Drive |
| `GITHUB_ACTIONS_PAT` | GitHub → Fine-grained PAT | Disparar workflows (`workflow_dispatch`) |

> **Não use o nome `GH_TOKEN`** — o Cursor pode sobrescrever com o token interno (`ghs_...`).

### Permissões do `GITHUB_ACTIONS_PAT`

Repositório: **ClassificacaoProcons** apenas.

| Permissão | Nível |
|-----------|--------|
| Actions | Read and write |
| Contents | Read |
| Metadata | Read |

Criar em: https://github.com/settings/personal-access-tokens/new

## O que já está no repositório

O arquivo `.cursor/environment.json`:

1. Cria o virtualenv e instala o pacote
2. Autentica o `gh` com `GITHUB_ACTIONS_PAT` (se existir)
3. Monta `credentials/gmail-*.json` a partir dos secrets

Depois de cadastrar os secrets, **inicie um novo Cloud Agent** (runs antigos não recebem secrets novos).

## Comandos que o agente deve usar

### Catch-up completo (padrão)

```bash
source .venv/bin/activate
contratos-webhook sync-all --dry-run --max-pages 50   # simular
contratos-webhook sync-all --max-pages 50             # aplicar
```

### Via GitHub Actions (se PAT configurado)

```bash
gh workflow run "Catch-up contratos (Autentique → Monday/Drive)" \
  -f dry_run=false \
  -f max_pages=50
```

### Acompanhar execução

```bash
gh run list --workflow="Catch-up contratos (Autentique → Monday/Drive)" --limit 3
gh run view <run-id> --log
```

## Checklist de validação (faça uma vez)

1. [ ] Secrets cadastrados no Cursor (6 itens acima)
2. [ ] Novo Cloud Agent iniciado
3. [ ] Pedir ao agente: *"Rode sync-all em dry-run e me mostre o resumo"*
4. [ ] Se OK: *"Rode sync-all sem dry-run"*
5. [ ] Pedir: *"Dispare o workflow Catch-up contratos com dry_run=false"*

## Limitações conhecidas

- O token interno do Cursor (`ghs_...`) **não** dispara workflows — precisa do `GITHUB_ACTIONS_PAT`.
- Sem `AUTENTIQUE_API_TOKEN` no Cursor, o agente **não** lista documentos do Autentique.
- GCP/IAM continua manual até a TI liberar permissões.
- Webhooks 24h (Autentique → Cloud Run) só após deploy no GCP.

## Mensagem pronta para o agente

Copie e cole em um novo Cloud Agent após configurar os secrets:

> Rode o catch-up de contratos: primeiro `contratos-webhook sync-all --dry-run`, depois sem dry-run se estiver ok. Se tiver `GITHUB_ACTIONS_PAT`, também dispare o workflow "Catch-up contratos" no GitHub. Me reporte created/updated/processed/failed.
