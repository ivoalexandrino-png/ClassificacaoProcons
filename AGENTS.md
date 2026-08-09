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
- `src/classificacao_procons/whatsapp/` — respostas automáticas no WhatsApp (IA + filtro jurídico)
- `src/classificacao_procons/radar/` — radar de editais de fomento (nacionais/internacionais → digest por e-mail)
- `src/classificacao_procons/cli.py` — CLI `procon-email`
- `src/classificacao_procons/juridico/cli.py` — CLI `juridico`
- `src/classificacao_procons/questor/cli.py` — CLI `questor`
- `src/classificacao_procons/whatsapp/cli.py` — CLI `whatsapp`
- `src/classificacao_procons/radar/cli.py` — CLI `radar`
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

Agente que lê o retrato do Questor (situação das certidões — Federal/PGFN, Estadual, Municipal, FGTS, Trabalhista — e mensagens da caixa postal eletrônica), detecta pendências (certidão positiva/vencida/a vencer/indisponível, mensagem não lida, prazo de ciência vencido/próximo) e, havendo problema **novo**, envia e-mail ao time fiscal e de contabilidade.

- Núcleo offline testável: `questor/analise.py` (regras), `questor/parser.py` (normalização de situação/datas/CNPJ), `questor/serialization.py` (JSON ↔ modelos). `ruff`/`pytest` rodam 100% offline.
- Envio de e-mail: `questor/notifier.py` via Gmail API (escopo `gmail.send`; `gmail.modify` também serve). Reautorizar com `procon-email auth` para o token ganhar o escopo de envio.
- Coleta no portal: `questor/portal.py` (Playwright, heurístico — os seletores/rotas precisam ser calibrados na primeira execução assistida contra o ambiente real do cliente).
- Dedup por `dedup_key` em `data/questor-alerted.json`: o mesmo problema não é reenviado a cada execução (use `--resend` para forçar).

Uso offline (sem portal), a partir de um snapshot JSON:

```bash
source .venv/bin/activate
questor analyze --snapshot snapshot.json                     # lista pendências (exit 1 se houver crítica)
questor check --snapshot snapshot.json --to fiscal@b4a.com,contabil@b4a.com --dry-run
```

Coleta + análise + alerta (produção; exige credenciais do Questor e token Gmail com envio):

```bash
questor check --portal-url "$QUESTOR_PORTAL_URL" --portal-login "$QUESTOR_LOGIN" \
  --portal-password "$QUESTOR_PASSWORD" --empresa "Empresa X" --cnpj 12345678000199 \
  --to fiscal@b4a.com,contabilidade@b4a.com
```

Segredos esperados (ausentes neste ambiente): `QUESTOR_PORTAL_URL`, `QUESTOR_LOGIN`, `QUESTOR_PASSWORD` e o token Gmail com escopo de envio.

### WhatsApp (respostas automáticas pessoal + profissional)

Conexão direta à conta via [Neonize](https://github.com/krypton-byte/neonize) (API não oficial — risco de banimento; uso por sua conta e risco).

- Núcleo offline: `whatsapp/risk.py`, `whatsapp/responder.py`, `whatsapp/history.py`. Testes mockam IA.
- Produção: `pip install -e ".[whatsapp]"`, `GEMINI_API_KEY` e/ou `OPENAI_API_KEY`, sessão em `data/whatsapp-session.sqlite3`.
- Histórico local: `data/whatsapp-bot-state.json` (dedup + últimas mensagens por chat).
- Tiers: `routine` (IA responde), `ambiguous` (pede contexto), `legal_high` (resposta segura sem orientação jurídica).

```bash
source .venv/bin/activate
whatsapp preview --chat-id 5511999999999@s.whatsapp.net --text "Oi, tudo bem?"
whatsapp run   # QR no terminal na 1ª execução; use --dry-run para testar sem enviar
```

Variáveis opcionais: `WHATSAPP_OWNER_NAME`, `WHATSAPP_PERSONA`, `WHATSAPP_SESSION_PATH`, `WHATSAPP_STATE_PATH`.

### Radar de editais (fomento e patrocínio → digest por e-mail)

Radar que monitora as principais fontes de fomento **nacionais e internacionais** e avisa os pesquisadores da universidade **assim que um edital/chamada relevante abre**, nas áreas de **Direito, Saúde, Administração e Educação**. Coleta os editais das fontes (RSS/Atom ou HTML), classifica cada um por área/abrangência/situação, seleciona os relevantes (descarta encerrados e fora de escopo) e envia um digest por e-mail com dedup para não reavisar o mesmo edital.

- Núcleo offline testável: `radar/parser.py` (classificação de área PT/EN, escopo, situação, datas), `radar/analise.py` (relevância + dedup), `radar/feeds.py` (parsing RSS/Atom/HTML — o `fetch` de rede fica isolado), `radar/serialization.py` (JSON ↔ modelos). `ruff`/`pytest` rodam 100% offline.
- Fontes: `radar/sources.py` (CNPq, CAPES, FINEP, FAPESP/FAPERJ/FAPEMIG, CONFAP, Fiocruz, DECIT/MS, IPEA, CNJ; Horizon Europe/ERC, NIH, NSF, Wellcome, Gates, Open Society, Ford, UNESCO, DAAD, Fulbright, British Council, BID). As URLs de listagem de oportunidades precisam ser calibradas na primeira execução assistida (mesma convenção do scraper do Questor); enquanto isso, use `snapshot` JSON.
- Envio de e-mail: `radar/notifier.py` reutiliza o `GmailSender` do Questor (escopo `gmail.send`/`gmail.modify`; reautorize com `procon-email auth`).
- Dedup por `dedup_key` em `data/radar-alerted.json`.

Uso offline (sem rede), a partir de um snapshot JSON de editais coletados:

```bash
source .venv/bin/activate
radar sources --scope internacional          # lista as fontes monitoradas
radar scan --snapshot editais.json           # lista os editais relevantes
radar scan --snapshot editais.json --areas saude,direito
radar check --snapshot editais.json --to pesquisa@uni.br,prppg@uni.br --dry-run
```

Coleta + análise + digest (produção; exige token Gmail com envio):

```bash
radar check --scope nacional --to pesquisa@uni.br,prppg@uni.br
```

Segredos esperados (ausentes neste ambiente): token Gmail com escopo de envio. As áreas padrão são as quatro pedidas (`direito,saude,administracao,educacao`); use `--areas` para restringir.

### Procon (backup SLA 30 min no GCP)

Scheduler → GitHub API: `docs/gcp-procon-github-scheduler.md` e `scripts/setup-gcp-github-procon-scheduler.sh` (exige `PROJECT_ID` + `GITHUB_ACTIONS_PAT` no ambiente de setup; **não** commitar PAT).
