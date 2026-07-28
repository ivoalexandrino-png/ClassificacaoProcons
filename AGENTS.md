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
- `src/classificacao_procons/cli.py` — CLI `procon-email`
- `src/classificacao_procons/juridico/cli.py` — CLI `juridico`
- `tests/` — testes unitários

## Segredos

Nunca commitar `credentials/`. Usar Secret Manager em produção.

## Cursor Cloud specific instructions

- Python é 3.12; as dependências ficam num virtualenv em `.venv` (o update script o cria e roda `pip install -e ".[dev]"`). Ative com `source .venv/bin/activate` ou chame binários direto (`.venv/bin/pytest`, `.venv/bin/ruff`, `.venv/bin/procon-email`). Os comandos de validação da seção acima assumem o venv ativo.
- `playwright install chromium` já roda no update script; o browser fica em `~/.cache/ms-playwright` e sobe headless sem `--with-deps`. É necessário só para o scraping do portal (comando `process`).
- `ruff check src tests` e `pytest` rodam 100% offline (os testes mockam Gmail/Drive/Monday/Gemini/Playwright).
- Os comandos que tocam serviços externos — `procon-email list/process/elaborate/register-monday` — exigem segredos ausentes neste ambiente: OAuth do Google (`credentials/gmail-oauth.json` + token), token do Monday (`MONDAY_API_TOKEN`) e `GEMINI_API_KEY`. Sem eles, valide via testes mockados e via o parser offline (`parse_procon_notification_body`), que é o núcleo do MVP.

### Contratos (Autentique → Monday/Drive)

Setup completo: `docs/cloud-agent-autonomia.md`.

**Signatários internos no Autentique:** Jan = `assinador@b4a.com.br`. Luciano = `juridico@b4a.com.br` **ou** nome exibido **Beauty For All** (mesma pessoa; o código trata os dois como Luciano no Controle).

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

### Procon (backup SLA 30 min no GCP)

Scheduler → GitHub API: `docs/gcp-procon-github-scheduler.md` e `scripts/setup-gcp-github-procon-scheduler.sh` (exige `PROJECT_ID` + `GITHUB_ACTIONS_PAT` no ambiente de setup; **não** commitar PAT).
