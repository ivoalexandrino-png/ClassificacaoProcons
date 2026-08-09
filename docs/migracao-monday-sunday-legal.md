# Migração Monday → Sunday (temas de legal) — estrutura da mudança

> Status: **planejamento**. Este documento estrutura a migração; **nada de código,
> board, dado ou infraestrutura foi alterado**. Serve de base para o time decidir e
> aprovar antes de qualquer execução.

## 1. Objetivo e escopo

Migrar os temas de **legal** que hoje vivem no Monday
(`beauty4all.monday.com/workspaces/2334257`) para o sistema **Sunday**
(`sunday.b4a.ai/workspaces/22`).

O que entra no escopo (domínio legal deste repositório):

- **Contratos** (Autentique → Controle Assinaturas + Contratos).
- **Jurídico** (intimações → prazos, audiências, processos judiciais/trabalhista, KPI).
- **Procon** (reclamações → quadro `procons`, processos administrativos).
- **Acessos / credenciais** (portais de tribunais e Questor).

Fora do escopo direto (mas dependem do mesmo quadro Acessos, atenção no cutover):
Questor (certidões) e o scraper de portais Procon, que só **leem** credenciais no Monday.

## 2. Como o sistema conversa com o Monday hoje

Toda chamada ao Monday passa por **um único ponto**:

- `src/classificacao_procons/monday/client.py`
  - `MONDAY_API_URL = "https://api.monday.com/v2"` (GraphQL)
  - `MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"` (upload de arquivo)
  - `MONDAY_API_VERSION = "2024-10"`
  - `_graphql_request(...)` — usada **direta ou indiretamente por todos os módulos** (`juridico/monday.py`, `contratos/monday_contracts.py`, `credentials/monday_board.py`, `juridico/casos.py`, `juridico/acessos.py`, scripts).
  - Autenticação: header `Authorization: <token>` + `API-Version`.

Isso é a maior vantagem da migração: existe **um choke point** para apontar o backend
para o Sunday. A dificuldade não está no transporte, e sim em **IDs de board/coluna/grupo**
e em **paridade de API** (ver §5 e §6).

## 3. Inventário — o que toca o Monday no domínio legal

| Tema | Módulo(s) | Board(s) Monday | Como o board é resolvido | Config |
|------|-----------|-----------------|--------------------------|--------|
| Contratos — Controle Assinaturas | `contratos/monday_contracts.py`, `contratos/controle_*.py` | Controle Assinaturas | **ID fixo** `5301515799` (`contratos/constants.py`) | colunas/grupos **hardcoded** |
| Contratos — Contratos | `contratos/monday_contracts.py` | Contratos | **ID fixo** `5385471914` | grupos por Tipo **hardcoded** |
| Jurídico — prazos | `juridico/monday.py` | `prazos` (grupo `prazos processos`) | nome ou `MONDAY_JURIDICO_BOARD_ID` | colunas **por título** |
| Jurídico — audiências | `juridico/monday.py` | `audiencias` | nome ou `MONDAY_AUDIENCIAS_BOARD_ID` | colunas **por título** |
| Jurídico — processos/KPI | `juridico/casos.py` | `processos judiciais`, `processos trabalhista`, `kpi - processos consumidores` | nome ou `MONDAY_PROCESSOS_BOARD_ID` / `MONDAY_TRABALHISTA_BOARD_ID` / `MONDAY_KPI_BOARD_ID` | colunas **por título** |
| Jurídico — acessos TJ | `juridico/acessos.py` | `acessos` (grupo TJ's) | nome ou `MONDAY_ACESSOS_BOARD_ID` | colunas **por título** |
| Procon — reclamações | `monday/client.py`, `response_pipeline.py`, `cli.py` | `procons` | nome ou `MONDAY_BOARD_ID` / `MONDAY_BOARD_NAME` | colunas **por título** |
| Credenciais Procon / Questor | `credentials/monday_board.py` | Acessos | **ID fixo** `7591024769` | colunas **por título** |

Observação-chave para a migração:

- Módulos que resolvem coluna **por título** (`juridico`, `procon`, `credentials`) são
  **resilientes**: se o Sunday preservar os títulos das colunas, funcionam sem editar código.
- **Contratos** resolve muita coisa por **ID fixo** de board, coluna e grupo
  (`constants.py`: `status`, `status_1__1`, `data0`, `link`, `long_text_mkvnwp6d`,
  grupos `novo_grupo`, `topics`, `contratos_jan__1`, …). Esses IDs **mudam** no Sunday e
  são o **maior ponto de recalibração**.

## 4. Superfície de configuração (env vars e secrets)

Variáveis de ambiente hoje em uso (todas continuam válidas; só mudam de valor no cutover):

- Token: `MONDAY_API_TOKEN` (GitHub secret `MONDAY_API_TOKEN`; no Cloud Run,
  secret `contratos-monday-token`).
- Seletores de board: `MONDAY_BOARD_ID`/`MONDAY_BOARD_NAME`, `MONDAY_JURIDICO_BOARD_ID`,
  `MONDAY_AUDIENCIAS_BOARD_ID`, `MONDAY_PROCESSOS_BOARD_ID`, `MONDAY_TRABALHISTA_BOARD_ID`,
  `MONDAY_KPI_BOARD_ID`, `MONDAY_ACESSOS_BOARD_ID`, `MONDAY_CREDENTIALS_BOARD_ID`,
  `QUESTOR_MONDAY_ITEM`.
- IDs fixos em código (contratos): `MONDAY_CONTROLE_ASSINATURAS_BOARD_ID`,
  `MONDAY_CONTRATOS_BOARD_ID` e o board de credenciais `7591024769`.

Workflows que carregam `MONDAY_API_TOKEN` (todos precisam repontar no cutover):
`questor-daily`, `procon-hourly`, `procon-proconsumidor-local`, `juridico-hourly`,
`jan-luciano-audit`, `controle-exclusion-analysis`, `contratos-*` (catch-up, sync-controle,
register-controle, link-controle, process-test, remediate, sync-after-agent-merge,
bootstrap-gcp), `agent-pr-automerge`.

## 5. Incógnitas sobre o Sunday (levantar antes de qualquer código)

O Sunday é interno da B4A e a URL espelha a do Monday (`/workspaces/<n>`), o que sugere um
clone/fork com modelo de dados semelhante. **Não está confirmado.** Antes de estimar esforço,
precisamos responder (fase de *discovery*):

1. **API**: o Sunday expõe GraphQL compatível com o schema do Monday
   (`boards`, `items_page`, `create_item`, `change_multiple_column_values`,
   `create_subitem`, `create_update`, `move_item_to_group`, `archive_item`,
   `items_page_by_column_values`)? Ou é REST/outro schema?
2. **Endpoint e auth**: qual a URL da API (`https://sunday.b4a.ai/api/...`?), qual header/token,
   há `API-Version`?
3. **Upload de arquivo**: existe equivalente ao `add_file_to_column` / `/v2/file` (multipart)?
4. **URL de item**: formato do link (hoje `https://<slug>.monday.com/boards/<b>/pulses/<i>`).
5. **IDs**: os board/coluna/grupo do Sunday são novos → precisa **tabela de-para** (§7).
6. **Webhooks**:
   - O receptor de webhook do Monday (`contratos/monday_webhook.py`, handshake `challenge`,
     eventos `create_pulse`/`item_created`) tem equivalente no Sunday?
   - As **automações internas** do Monday (ex.: Controle "Assinado" → cria item em Contratos;
     filas Jan/Luciano) precisam ser **recriadas** no Sunday — elas não estão no código.
7. **Paridade de recursos**: colunas `status`/`dropdown` com labels, `board_relation`
   (conexão de quadros usada em `juridico/casos.py`), subitens, grupos dinâmicos.

> A integração com o **Autentique** não muda: o webhook do Autentique aponta para o nosso
> Cloud Run. Só muda o destino (Monday → Sunday) do que o serviço grava.

## 6. Estratégia de migração (faseada, com rollback)

Proposta em fases; cada fase é aprovável isoladamente e **não** quebra a operação atual.

### Fase 0 — Discovery e calibração (sem código)

- Responder §5 com acesso assistido ao Sunday (mesma convenção do scraper do Questor).
- Levantar IDs reais de board/coluna/grupo no Sunday e preencher a tabela de-para (§7).
- Confirmar formato de webhook e recriar (no Sunday) as automações internas do Monday.

### Fase 1 — Camada de abstração no código (comportamento inalterado)

- Introduzir seleção de backend por configuração no **único choke point**
  (`monday/client.py`): endpoint/base-URL, token e "dialeto" da API configuráveis
  (ex.: `LEGAL_BACKEND=monday|sunday`, `LEGAL_API_URL`, `LEGAL_API_TOKEN`).
- Mover os IDs fixos de Contratos (`constants.py`) para configuração parametrizável por
  backend, para permitir Monday e Sunday sem editar código.
- Nada de comportamento novo: com `LEGAL_BACKEND=monday`, tudo roda idêntico a hoje.
- Cobertura de testes: os testes atuais mockam o transporte; manter verde e adicionar casos
  do dialeto Sunday.

### Fase 2 — Migração de dados

- Exportar itens dos boards legais do Monday e importar no Sunday, **preservando as chaves
  estáveis** (Autentique ID nos contratos; protocolo/CPF no Procon; CNJ no jurídico; NSU no
  Questor). Sem essas chaves, a deduplicação (§8) quebra no cutover.
- Validar contagens e amostragem item a item antes de considerar migrado.

### Fase 3 — Dual-run / validação

- Rodar leitura no Sunday em paralelo (dry-run) e comparar com o Monday.
- Repontar 1 workflow de baixo risco primeiro (ex.: `questor-daily`, que só lê Acessos).

### Fase 4 — Cutover + rollback

- Trocar `LEGAL_BACKEND`/secrets para Sunday em todos os workflows e no Cloud Run.
- **Rollback**: voltar `LEGAL_BACKEND=monday` e os secrets antigos — como a Fase 1 mantém os
  dois backends, o rollback é uma troca de variável, não um redeploy de código.

## 7. Tabela de-para de IDs (a preencher na Fase 0)

| Board (legal) | Monday ID | Sunday ID | Colunas/grupos a remapear |
|---------------|-----------|-----------|----------------------------|
| Controle Assinaturas | `5301515799` | _(a levantar)_ | `status`, `status_1__1` (Tipo), `data0`, `link`, `long_text_mkvnwp6d`, grupos Jan/Luciano/Assinados |
| Contratos | `5385471914` | _(a levantar)_ | grupos por Tipo (`topics`, `novo_grupo*`, `contratos_jan__1`, …) |
| Acessos (credenciais) | `7591024769` | _(a levantar)_ | Login/Senha/Link, grupos Procon/TJ's |
| prazos | por nome/env | _(a levantar)_ | resolvidas por título (validar títulos) |
| audiencias | por nome/env | _(a levantar)_ | resolvidas por título |
| processos judiciais / trabalhista / KPI | por nome/env | _(a levantar)_ | `board_relation`, status/labels |
| procons | por nome/env | _(a levantar)_ | resolvidas por título |

## 8. Estado de deduplicação (risco no cutover)

- `data/questor-alerted.json` — chave por certidão/empresa + **NSU** (derivada do portal, não do
  item Monday). **Estável** na migração.
- `data/radar-alerted.json` — `dedup_key` derivada da fonte. **Estável**.
- **Contratos** — a dedup usa o **Autentique ID** gravado no link de assinatura do item, além
  de varredura por **coluna/grupo com IDs fixos**. Estável **se e somente se** a migração
  levar o Autentique ID; os IDs de coluna/grupo **precisam** ser remapeados (§7).
- **Procon** — dedup por **protocolo/CPF** via `items_page_by_column_values`. Depende de o
  Sunday suportar essa consulta e preservar os valores.
- **Cache de dedup nos workflows** (`actions/cache`) não precisa migrar, mas convém limpar no
  cutover para evitar falso-positivo cruzando os dois sistemas.

## 9. Riscos e pontos de atenção

- **Nível de risco: ALTO.** Toca integrações externas, automações de assinatura de contratos e
  credenciais — áreas sensíveis (exigem revisão humana, por regra interna).
- **Paridade de API** é a maior incerteza: se o Sunday não for GraphQL-compatível, a Fase 1
  vira um adaptador de dialeto, não só uma base-URL.
- **Automações internas** (filas Jan/Luciano, Controle→Contratos) vivem no Monday, **não no
  código** — precisam ser recriadas no Sunday e testadas ponta a ponta.
- **IDs fixos de Contratos** são o maior ponto de recalibração de código.
- **Nada deve ser migrado ou repontado sem confirmação humana** (efeitos colaterais: e-mails,
  criação de itens, mudança de acesso).

## 10. Próximos passos (decisão do time)

1. Validar este escopo e a ordem das fases.
2. Confirmar as incógnitas do §5 (acesso assistido ao Sunday) e preencher o de-para do §7.
3. Só então abrir as tarefas de implementação (Fase 1 em diante), uma por tema.

## Perguntas em aberto

- O Sunday expõe API GraphQL compatível com o Monday, ou precisaremos de um adaptador?
- Existe migração de dados oficial Monday→Sunday (ferramenta do B4A) ou faremos export/import?
- As automações internas (Jan/Luciano, Controle→Contratos) já existem no Sunday ou serão
  recriadas por nós?
- O cutover será por tema (contratos, jurídico, procon, acessos) ou tudo de uma vez?
