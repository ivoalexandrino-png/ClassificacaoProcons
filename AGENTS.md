# AGENTS.md

## Repositório

- **base_branch:** `main`
- **pr_qa_target:** `develop` (criar quando existir fluxo B4A completo; por ora PR direto em `main` se não houver develop)
- **pr_prod_target:** `main`

## Validação obrigatória

```bash
pip install -e ".[dev]"
ruff check src tests
pytest
```

## Estrutura

- `src/classificacao_procons/email/` — parser e cliente Gmail
- `src/classificacao_procons/juridico/` — agente jurídico (intimações, DataJud, providências)
- `src/classificacao_procons/questor/` — agente Questor (certidões negativas + caixa postal fiscal → alerta por e-mail)
- `src/classificacao_procons/cli.py` — CLI `procon-email`
- `src/classificacao_procons/juridico/cli.py` — CLI `juridico`
- `src/classificacao_procons/questor/cli.py` — CLI `questor`
- `tests/` — testes unitários

## Segredos

Nunca commitar `credentials/`. Usar Secret Manager em produção.

## Cursor Cloud specific instructions

- Python é 3.12; as dependências ficam num virtualenv em `.venv` (o update script o cria e roda `pip install -e ".[dev]"`). Ative com `source .venv/bin/activate` ou chame binários direto (`.venv/bin/pytest`, `.venv/bin/ruff`, `.venv/bin/procon-email`). Os comandos de validação da seção acima assumem o venv ativo.
- `playwright install chromium` já roda no update script; o browser fica em `~/.cache/ms-playwright` e sobe headless sem `--with-deps`. É necessário só para o scraping do portal (comando `process`).
- `ruff check src tests` e `pytest` rodam 100% offline (os testes mockam Gmail/Drive/Monday/Gemini/Playwright).
- Os comandos que tocam serviços externos — `procon-email list/process/elaborate/register-monday/sla-check` — exigem segredos ausentes neste ambiente: OAuth do Google (`credentials/gmail-oauth.json` + token), token do Monday (`MONDAY_API_TOKEN`) e `GEMINI_API_KEY`. Sem eles, valide via testes mockados e via o parser offline (`parse_procon_notification_body`), que é o núcleo do MVP.

### Contratos (Autentique → Monday/Drive)

Setup completo: `docs/cloud-agent-autonomia.md`. Reconciliação Controle: `docs/controle-autentique-reconciliacao.md`.

**Signatários internos no Autentique (mapeamento para filas Jan/Luciano no Controle):**

| Atribuir a **Jan** | Atribuir a **Luciano** |
|--------------------|-------------------------|
| Nome **Jan** (ex.: Jan Riehle), **Assinador** | Nome **Luciano**, **Beauty For All** |
| E-mail `assinador@b4a…` (variações) | E-mail `juridico@b4a…` (variações) |

Implementação: `signer_identity.py` (e-mail ou nome exibido). Coluna **Quem Assina** no Monday: **Assinador** / **Luciano**.

**Controle Assinaturas (duas filas):** cada documento gera **dois itens** no Monday — grupo **Jan** (com coluna **Tipo**, dispara automação → Contratos quando **Assinado**) e grupo **Luciano** (sem Tipo, só acompanhamento). Em regra o Luciano assina antes do Jan; o status dos dois itens é sincronizado via webhook/sync. Não é necessário duplicar manualmente ao concluir as assinaturas.

**Deduplicação Autentique ↔ Controle (não confundir com mesmo fornecedor):**

1. **Autentique ID** no link do item → mesma chave; nunca criar outro par.
2. **Título idêntico** (normalizado) → mesmo contrato.
3. **Título parecido** só com evidência forte (ex.: um título contém o outro com ≥18 caracteres; ou ≥3 tokens distintivos iguais; ou ≥2 tokens + mesma data/`YYYYMM` no nome). **Não** fundir só porque o fornecedor coincide (ex.: vários `*_BrassHill` com meses diferentes).
4. Legado sem ID e título diferente (ex. minuta no Autentique vs contrato B2B no Monday) → colar o **Autentique ID** no item existente ou alinhar o título; o sync não adivinha.

- `OPENAI_API_KEY` (fallback do `elaborate` quando Gemini atinge cota; recomendado em produção junto com `GEMINI_API_KEY`)

Catch-up em lote (recomendado):

```bash
source .venv/bin/activate
contratos-webhook sync-all --dry-run --max-pages 50
contratos-webhook sync-all --max-pages 50
```

Disparar workflow no GitHub (requer `GITHUB_ACTIONS_PAT` configurado no start hook):

```bash
gh workflow run "Catch-up contratos (Autentique → Monday/Drive)" -f dry_run=false -f max_pages=50
```

**Automação sem intervenção:** merge em `main` que altere `src/classificacao_procons/contratos/**` dispara o workflow **Sync Controle Assinaturas** (reparo Jan/Luciano + reconcile, sem import em massa de já assinados). O cron horário (`:15`) usa os mesmos parâmetros.

**Pausa de criação no Controle:** por padrão **não** criamos novos itens no quadro (`CONTROLE_PAUSE_CREATE=true` ou variável ausente). Sync, webhooks `document.created` e `register-controle` continuam com vínculo legado, reparo de filas Jan/Luciano e atualização de status. Para criar faltantes de propósito: `CONTROLE_PAUSE_CREATE=false` ou `contratos-webhook sync-controle --allow-create`.

### Questor (certidões negativas + caixa postal fiscal)

Agente que lê o retrato do Questor Zen (`https://<conta>.zen.questor.com.br`) — situação das certidões (Federal/PGFN, Estadual, Municipal, FGTS, etc.) e mensagens da caixa postal (DTE/e-CAC) — detecta pendências e, havendo problema **novo**, envia e-mail ao time fiscal e de contabilidade.

**Integração (calibrada contra o portal real):** o login web (`#Email`/`#SenhaEntrar` + consentimento de cookies) autentica e o agente consome os endpoints JSON internos (DevExtreme) usados pelos grids:

- Certidões: `POST /escritorio/cnd/certidaoempresa/listarcertidaoempresa`
- Caixa postal: `POST /escritorio/dte/capturacaixapostal/listar`

Buscamos o dataset completo (`take` alto) e filtramos em Python — mais robusto que raspar o DOM paginado. Enums do Questor mapeados em `questor/parser.py`:

- `SituacaoCertidao`: `0=Irregular`, `1=Regular`, `2=Neutro`, `3=Falha`, `5=Restrição`.
- `Leitura`: `0=Não lido`, `1=Leitura pendente`, `2=Lido`. `Relevancia`: `0=Não`, `1=Sim`.

**Regras (`questor/analise.py`, offline e testável):** certidão Irregular/Restrição → crítico; vencida (data/estado) → crítico; a vencer ≤ janela → aviso; Falha → aviso (indisponível); Regular/Neutro → ok. Caixa postal: prazo de ciência (`ExibidaAte`) vencido/próximo → crítico; não lida → aviso.

**Política de caixa postal (`questor/policy.py`):** o backlog de não lidas é grande e o flag "Relevante" é pouco usado; por isso a seleção é configurável (`--caixa-mode`): `relevante_ou_prazo` (default), `relevantes`, `recentes`, `todas`. O total não lido por domicílio vai como nota de contexto no e-mail.

**Credenciais:** lidas do board **Acessos** do Monday (`credentials/monday_board.py`, board `7591024769`) pelo item **"Questor - Certidões - Ivo"** (há dois itens homônimos; o com sufixo "- Ivo" é o ativo). Override: env `QUESTOR_MONDAY_ITEM`. Requer `MONDAY_API_TOKEN`.

**Envio de e-mail:** `questor/notifier.py` via Gmail API. Usa o escopo `gmail.modify` já concedido (que também autoriza envio) — **não** adicionar `gmail.send` a `GOOGLE_SCOPES` (força upgrade de escopo e quebra o refresh dos tokens já emitidos com `invalid_scope`).

**Dedup:** `data/questor-alerted.json` (chave por certidão/empresa e por NSU da mensagem); o mesmo problema não é reenviado (use `--resend` para forçar).

Uso offline (a partir de um snapshot JSON, sem portal/segredos):

```bash
source .venv/bin/activate
questor analyze --snapshot snapshot.json   # lista pendências (exit 1 se houver crítica)
questor check --snapshot snapshot.json --to fiscal@b4a.com,contabil@b4a.com --dry-run
```

Coleta + análise + alerta (produção; credenciais vêm do Monday):

```bash
questor check --portal-url https://b4a.zen.questor.com.br/ --empresa "B4A / MMKT" \
  --to fiscal@b4a.com,contabilidade@b4a.com --caixa-mode relevante_ou_prazo
```

Playwright: rodar `playwright install chromium` (o update script já faz). O login do Questor é sessão única — evite acessos concorrentes.

### Procon (backup SLA 30 min no GCP)

Scheduler → GitHub API: `docs/gcp-procon-github-scheduler.md` e `scripts/setup-gcp-github-procon-scheduler.sh` (exige `PROJECT_ID` + `GITHUB_ACTIONS_PAT` no ambiente de setup; **não** commitar PAT).
