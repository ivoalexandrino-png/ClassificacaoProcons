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
- `src/classificacao_procons/cli.py` — CLI `procon-email`
- `tests/` — testes unitários

## Segredos

Nunca commitar `credentials/`. Usar Secret Manager em produção.

## Cursor Cloud specific instructions

- Python 3.12 project. Dependencies live in a virtualenv at `.venv` (created by the startup update script). The update script does NOT auto-activate it for interactive sessions — run `. .venv/bin/activate` first, or call tools directly (e.g. `.venv/bin/pytest`, `.venv/bin/ruff`, `.venv/bin/procon-email`).
- Standard validation (`ruff check src tests`, `pytest`) is documented above; the full suite (98 tests) runs fully offline with no secrets.
- The CLIs (`procon-email`, `procon-portal`, `procon-drive`, `contratos-webhook`) are the app entry points. The email parser core (`classificacao_procons.email.parse_procon_notification_body`) works offline; live pipelines need external credentials (see below).
- `procon-portal` / `procon-email process` drive the Procon site via Playwright. The update script installs Chromium (`playwright install chromium`); its cache is `~/.cache/ms-playwright`.
- Live end-to-end flows (Gmail, Drive, Monday, Gemini, Autentique, Procon portal) require secrets/credentials not present in this environment: Google OAuth JSON at `credentials/gmail-oauth.json` (+ token), plus env vars like `MONDAY_API_KEY`, `GEMINI_API_KEY`, etc. Without them, `process`/`list`/`elaborate` fail fast asking to run `procon-email auth`. This is expected, not an environment bug.
