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
- `src/classificacao_procons/litigio/` — agente de monitoramento de litígio (DJEN → providência → Monday)
- `src/classificacao_procons/litigio_cli.py` — CLI `litigio-agent`
- `tests/` — testes unitários

## Segredos

Nunca commitar `credentials/`. Usar Secret Manager em produção.

## Cursor Cloud specific instructions

- Python é 3.12; as dependências ficam num virtualenv em `.venv` (o update script o cria e roda `pip install -e ".[dev]"`). Ative com `source .venv/bin/activate` ou chame binários direto (`.venv/bin/pytest`, `.venv/bin/ruff`, `.venv/bin/procon-email`). Os comandos de validação da seção acima assumem o venv ativo.
- `playwright install chromium` já roda no update script; o browser fica em `~/.cache/ms-playwright` e sobe headless sem `--with-deps`. É necessário só para o scraping do portal (comando `process`).
- `ruff check src tests` e `pytest` rodam 100% offline (os testes mockam Gmail/Drive/Monday/Gemini/Playwright).
- Os comandos que tocam serviços externos — `procon-email list/process/elaborate/register-monday` — exigem segredos ausentes neste ambiente: OAuth do Google (`credentials/gmail-oauth.json` + token), token do Monday (`MONDAY_API_TOKEN`) e `GEMINI_API_KEY`. Sem eles, valide via testes mockados e via o parser offline (`parse_procon_notification_body`), que é o núcleo do MVP.
