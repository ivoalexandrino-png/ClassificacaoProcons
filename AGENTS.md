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

Secrets necessários no Cursor: `MONDAY_API_TOKEN`, `AUTENTIQUE_API_TOKEN`, `GEMINI_API_KEY`, `GMAIL_OAUTH_JSON`, `GMAIL_TOKEN_JSON`, `GITHUB_ACTIONS_PAT`.

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
