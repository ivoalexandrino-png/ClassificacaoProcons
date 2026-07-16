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

Projeto Python puro (CLI + webhook HTTP), sem UI web. Python 3.12 já está disponível.

- **Instalação/deps:** já cobertas pelo update script (`pip install --break-system-packages -e ".[dev]"` + `python3 -m playwright install chromium`). O ambiente é Debian "externally-managed", por isso o `--break-system-packages` é necessário; não há `python3-venv` disponível via apt, então instalamos no Python do sistema.
- **PATH:** os consoles scripts (`procon-email`, `procon-portal`, `procon-drive`, `contratos-webhook`) ficam em `~/.local/bin`. Já adicionado ao `~/.bashrc`; em shells que não carregam o bashrc, use `python3 -m classificacao_procons.cli ...` ou exporte `PATH="$HOME/.local/bin:$PATH"`.
- **Validação:** `ruff check src tests` e `pytest` (98 testes, todos mockam serviços externos — rodam sem credenciais).
- **Comandos que exigem credenciais:** `procon-email process/list/elaborate` e o pipeline exigem OAuth do Google (`credentials/gmail-token.json`), além de tokens Monday/Gemini conforme o fluxo. Sem esses segredos eles falham com "Google ainda não conectado" — isso é esperado, não é bug do ambiente.
- **Serviços que rodam localmente sem segredos:** `contratos-webhook serve` / `serve-monday` (servidor HTTP; `serve-monday` responde ao handshake `challenge` do Monday). O parser de e-mail (`parse_procon_notification_body`) roda standalone e é o núcleo testável offline.
- **Playwright:** o `procon-portal` usa Chromium via Playwright (binário já instalado pelo update script); só executa de verdade contra o portal real do Procon com código de acesso válido.
