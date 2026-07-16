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

- Projeto Python puro (>=3.11); dependências ficam num virtualenv em `.venv/` (gitignored). O update script cria/atualiza esse venv, então antes de rodar qualquer comando ative-o: `source .venv/bin/activate` (ou prefixe com `.venv/bin/`, ex.: `.venv/bin/pytest`).
- Validação padrão está em `## Validação obrigatória` acima (`ruff check src tests` e `pytest`); rode-os dentro do venv.
- Não há UI/web app. Os produtos são CLIs (`procon-email`, `procon-portal`, `procon-drive`, `contratos-webhook`) mais um servidor HTTP de webhooks (`contratos-webhook serve` para Autentique e `contratos-webhook serve-monday` para Monday).
- Servidor de webhook não exige credenciais para subir; o handshake de challenge do Monday (`POST /webhooks/monday` com `{"challenge":"..."}`) ecoa o token e é a forma mais simples de smoke-test sem segredos.
- A maioria dos fluxos reais precisa de segredos externos (OAuth Gmail em `credentials/gmail-oauth.json`, `GEMINI_API_KEY`, token do Monday, Autentique). Sem eles, dá para testar o parser (`classificacao_procons.email.parse_procon_notification_body`), os testes unitários e o servidor de webhook.
- `playwright` é dependência, mas o browser não é instalado pelo update script. Para os fluxos de portal (`procon-portal` / `procon-email process`) rode `.venv/bin/playwright install chromium` (mais deps de sistema). Não é necessário para lint/testes.
