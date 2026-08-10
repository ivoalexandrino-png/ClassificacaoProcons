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

**Parte A — transporte configurável: FEITO** (`monday/backend.py`).

- Backend selecionável por `LEGAL_BACKEND` (`monday` **padrão** | `sunday`), resolvido no
  **único choke point** (`monday/client.py::_graphql_request` e `upload_file_to_column`).
- Endpoint/versão/token parametrizáveis: `LEGAL_API_URL`, `LEGAL_FILE_API_URL`,
  `LEGAL_API_VERSION`, `LEGAL_API_TOKEN` (genéricos) e `SUNDAY_API_URL`, `SUNDAY_FILE_API_URL`,
  `SUNDAY_API_VERSION`, `SUNDAY_API_TOKEN` (específicos do Sunday).
- Token: prioridade backend-específico → `LEGAL_API_TOKEN` → `MONDAY_API_TOKEN` (fallback ao
  segredo compartilhado no cutover). `get_api_token_from_env()` passou a delegar a isso.
- Comportamento padrão **idêntico** a hoje: sem `LEGAL_BACKEND`, tudo aponta para o Monday
  (`https://api.monday.com/v2`, versão `2024-10`, `MONDAY_API_TOKEN`). Cobertura: 943 testes
  verdes (11 novos em `tests/test_monday_backend.py`).
- `LEGAL_BACKEND=sunday` sem `SUNDAY_API_URL` falha com erro claro (não cai no Monday por engano).

**Parte B — IDs por backend: PENDENTE (após discovery).**

- Mover os IDs fixos de Contratos (`constants.py`) para configuração parametrizável por backend.
  Fica para depois de termos o de-para do Sunday (§7), para não retrabalhar.

#### Como usar a sonda de discovery (assim que houver endpoint/token do Sunday)

O comando `juridico boards` lista os quadros visíveis (id, grupos, colunas) **do backend ativo** —
serve para responder se o Sunday é GraphQL-compatível e para preencher o de-para (§7):

```bash
# hoje (Monday, comportamento atual)
juridico boards --filter contratos

# quando o Sunday estiver disponível (não muda nada no Monday):
LEGAL_BACKEND=sunday SUNDAY_API_URL=https://sunday.b4a.ai/api/... \
  SUNDAY_API_TOKEN=<token> juridico boards
```

Se o Sunday responder com o mesmo schema, o de-para sai direto daí. Se falhar/for outro
formato, confirma-se a necessidade do adaptador de dialeto (§11.2).

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

Sunday workspace **22** = "Support - Finance, Legal, People" (ver §12). IDs confirmados no
discovery de 2026-08-10; quadros ainda **vazios** e com colunas genéricas do template.

| Board (legal) | Monday ID | Sunday ID (ws 22) | Colunas/grupos a remapear |
|---------------|-----------|-------------------|----------------------------|
| Controle Assinaturas | `5301515799` | **`77`** "Legal - Controle de Assinaturas - Jan & Luciano" | `status`, `status_1__1` (Tipo), `data0`, `link`, `long_text_mkvnwp6d`, grupos Jan/Luciano/Assinados |
| Contratos | `5385471914` | _(não existe no ws 22 — definir)_ | grupos por Tipo (`topics`, `novo_grupo*`, `contratos_jan__1`, …) |
| Acessos (credenciais) | `7591024769` | **`78`** "Legal - Acessos" | Login/Senha/Link (hoje o board Sunday só tem colunas genéricas `name/status/owner/date/area`) |
| prazos | por nome/env | _(não localizado — talvez `74` "Cronograma + Processos Finance")_ | resolvidas por título |
| audiencias | por nome/env | **`72`** "Legal - Audiências" | resolvidas por título |
| processos judiciais / trabalhista / KPI | por nome/env | _(a definir — possível `74`)_ | `board_relation`, status/labels |
| procons | por nome/env | _(não existe no ws 22 — definir)_ | resolvidas por título |
| _(sem correspondente Monday)_ | — | `79` "Legal - Seguros", `70` "Weekly Support" | novos no Sunday |

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

## 11. Próximos passos — migrar os quadros menos relevantes primeiro

Estratégia de "canário": começar pelos quadros de **menor criticidade e menor acoplamento**,
para provar a integração com o Sunday ponta a ponta antes de tocar Contratos/prazos.

### 11.1 Ranking por relevância/risco (do mais fácil ao mais crítico)

| Ordem | Quadro | Escrita? | Acoplamento | Por que nesta posição |
|-------|--------|----------|-------------|------------------------|
| 1 | **Acessos** (credenciais) | **Só leitura** | Nenhum (resolve por título) | Zero risco de escrita: dá para ler do Sunday em *dry-run* e comparar com o Monday. Canário técnico ideal. Atenção: guarda senhas (sensível) e é dependência de Questor/Procon — manter Monday como fonte até validar. |
| 2 | **KPI - Processos Consumidores** | Escrita (status/data) | Médio (busca por CNJ) | Quadro de métricas/relatório, menor criticidade operacional. Bom primeiro quadro de **escrita**. |
| 3 | **audiencias** | Escrita | Médio (alimentado por automação do Monday a partir de Processos) | Secundário ao de prazos; volume menor. |
| 4 | **procons** | Escrita | Baixo (standalone, por título) | Operacionalmente relevante (prazos regulatórios), mas isolado. |
| 5 | **prazos** | Escrita | Alto (prazos fatais + dedup por CNJ) | Erro aqui = prazo perdido; migrar só depois de validar o fluxo. |
| 6 | **processos judiciais / trabalhista** | Escrita | Alto (`board_relation`, quadro-mestre) | Origem dos casos; conecta prazos/audiências/KPI. |
| 7 | **Contratos** (Controle + Contratos) | Escrita | Máximo (IDs fixos, webhook Autentique, automações internas Jan/Luciano) | Mais crítico e mais frágil; **por último**. |

Recomendação: **Acessos (dry-run de leitura) como canário**, depois **KPI** como primeiro quadro
de escrita. Só avançar para 4–7 após validar 1–2.

### 11.2 Bloqueio comum a TODOS os quadros (o que precisamos primeiro)

Nada pode ser migrado sem o *discovery* da API do Sunday (§5). Precisamos, do time B4A:

1. **Endpoint + token do Sunday** (de teste, para este ambiente ou sessão assistida).
2. **Tipo de API**: ~~GraphQL compatível?~~ **Respondido (§12): REST próprio (NestJS), auth
   `Bearer`.** → precisamos do **cliente REST do Sunday** atrás do mesmo choke point (Fase 1B).
3. **Upload de arquivo** e **formato de URL de item** no Sunday.
4. Existe **ferramenta oficial de migração de dados** Monday→Sunday, ou faremos export/import?

### 11.3 Checklist por quadro (repetir para cada canário)

1. Criar/localizar o quadro correspondente no Sunday e preencher o de-para de IDs (§7).
2. (Escrita) Migrar dados preservando as **chaves estáveis** (§8): protocolo/CPF, CNJ, NSU.
3. Repontar **apenas** a config daquele quadro (env/secret) para o Sunday.
4. Rodar em *dry-run*/paralelo e comparar com o Monday.
5. Recriar no Sunday as **automações internas** que o quadro dependia (se houver).
6. Cutover do quadro; manter rollback por variável (Fase 1).

### 11.4 O que já foi adiantado em código (sem depender do Sunday)

- **FEITO**: transporte configurável no choke point (`monday/backend.py`) — base-URL/endpoint/
  versão/token por backend, padrão Monday, 943 testes verdes. Ver Fase 1, Parte A.
- **PENDENTE (após discovery)**: IDs fixos de Contratos (`constants.py`) por backend e, se o
  Sunday não for GraphQL-compatível, o adaptador de dialeto — ambos dependem da resposta do
  §11.2 para não retrabalhar.

## 12. Discovery do Sunday — CONFIRMADO (2026-08-10)

Sondagem read-only com um Personal Access Token (`sun_pat_…`) real. **Resultado decisivo: o
Sunday NÃO é o Monday.** É uma API **REST própria** (NestJS em Cloud Run), não o GraphQL do Monday.

### 12.1 Transporte e autenticação

- Base da API: `https://sunday-api-757613635701.us-central1.run.app` (descoberto no bundle do
  front: `environment.apiBaseUrl`). O front web fica em `https://sunday.b4a.ai` (Angular SPA).
- **Auth: `Authorization: Bearer <PAT>`** (confirmado: `GET /auth/me` → 200 com o perfil do
  usuário). Token **cru** estilo Monday (`Authorization: <token>`) → **401**.
- Tokens são gerenciados em `/auth/me/api-tokens` (create/list/revoke) — origem dos `sun_pat_…`.
- Modelo de permissão por token/perfil: algumas rotas retornam 403 conforme o papel.

### 12.2 Superfície REST mapeada (somente leitura testada)

| Método | Rota | Retorno |
|--------|------|---------|
| GET | `/auth/me` | perfil do usuário |
| GET | `/workspaces` / `/workspaces/{id}` | workspaces (id, name, slug, board_count, …) |
| GET | `/boards` e `/boards?workspace_id={id}` | lista de boards (com `status_set` de labels) |
| GET | `/boards/{id}` | board (inclui `status_set`, `capabilities`, `members`) |
| GET | `/boards/{id}/items` | itens (array; vazio nos boards atuais) |
| GET | `/boards/{id}/groups` | grupos (`id`, `board_id`, `name`, `color`, `position`) |
| GET | `/boards/{id}/columns` | colunas (`id`, `key`, `type`, `label`, `settings`, `is_system`) |

Colunas têm `key`/`type`/`label` (ex.: `name/text/Nome`, `status/status/Status`, `owner/people`,
`target_date/date`, `area/dropdown`). Nada de `items_page_by_column_values`, `change_multiple_
column_values`, subitens Monday, etc. — a semântica é REST por recurso.

### 12.3 Estado dos boards legais no Sunday

Workspace `22` "Support - Finance, Legal, People" (6 boards): `78` Legal - Acessos, `72` Legal -
Audiências, `77` Legal - Controle de Assinaturas - Jan & Luciano, `79` Legal - Seguros, `74`
Cronograma + Processos Finance, `70` Weekly Support. Os boards estão **vazios** (0 itens) e com as
**colunas genéricas do template** (ex.: Acessos não tem Login/Senha/Link ainda). Ou seja, o lado
Sunday é andaime: falta criar colunas de domínio e importar dados.

### 12.4 Impacto na estratégia (revisão)

- **Fase 1A (transporte configurável) continua válida e necessária**, mas **insuficiente** sozinha:
  além de base-URL/token/versão, o Sunday exige **auth `Bearer`** (hoje o cliente manda o token cru).
- **Fase 1B deixa de ser "adaptador só se preciso" e passa a ser obrigatória**: um **cliente REST
  do Sunday** implementando nossas operações (listar/criar item, setar valores de coluna, mover
  grupo, upload) atrás do **mesmo choke point**. Não é troca de base-URL — é uma implementação nova.
- **Escrita ainda não mapeada**: os endpoints de `POST`/`PATCH` (criar item, setar coluna, criar
  grupo, upload de arquivo) **não** foram sondados de propósito — escrever num sistema legal ao vivo
  exige confirmação humana (regra interna). Precisamos da **doc da API** ou de **permissão para
  escritas de teste** num board sandbox.

### 12.5 Segurança

O PAT usado foi **colado em texto puro no chat** → recomendação: **revogar/rotacionar** esse token
no Sunday e recadastrá-lo como **Runtime Secret** (`SUNDAY_API_TOKEN`) no Cloud Agents → Secrets. O
token **não** foi gravado em arquivo nem versionado; só usado em memória para o discovery read-only.

### 12.6 Cliente REST do Sunday — leitura FEITA

Implementado o pacote `src/classificacao_procons/sunday/` (client + parser + modelos + CLI
`sunday`), cobrindo o **caminho de leitura** e validado **ao vivo** contra a API real:

- `sunday me` → perfil autenticado (`/auth/me`).
- `sunday workspaces` / `sunday boards --workspace-id 22` → workspaces e os 6 boards legais.
- `sunday board <id>` → board + colunas + grupos + itens (ex.: `78 Legal - Acessos`).

Configuração por `SUNDAY_API_URL` + `SUNDAY_API_TOKEN` (auth `Bearer`). Testes offline com os
payloads reais (`tests/test_sunday_parser.py`, `tests/test_sunday_client.py`) — suíte em 965 verdes.

### 12.7 Próximos passos (após leitura)

1. **Escrita**: mapear/confirmar os endpoints `POST`/`PATCH` (criar item, setar coluna, criar
   grupo, upload) — precisa de doc da API ou board sandbox (não sondamos escrita no sistema ao vivo).
2. **Colunas de domínio**: os boards do Sunday estão com colunas genéricas; definir quem cria as
   colunas (Login/Senha/Link em Acessos etc.) — nós via API ou o time no app.
3. **Canário Acessos**: quando o board `78` tiver dados, comparar a leitura Sunday × Monday (dry-run).
4. **Roteamento por backend**: unificar Monday (GraphQL) e Sunday (REST) atrás de uma interface de
   "board provider" comum, selecionada por `LEGAL_BACKEND`.
5. **Rotacionar o PAT** exposto no chat (pendente — o usuário optou por pular por ora).

## Perguntas em aberto

- ~~O Sunday expõe API GraphQL compatível com o Monday?~~ **Respondido (§12): não — é REST próprio
  (NestJS), auth `Bearer`. Precisamos do cliente REST do Sunday (Fase 1B).**
- Onde está a **documentação da API REST do Sunday** (endpoints de escrita: criar item, setar
  coluna, criar grupo, upload)? Há board sandbox para escritas de teste?
- Existe migração de dados oficial Monday→Sunday (ferramenta do B4A) ou faremos export/import?
- Os boards do Sunday (ws 22) estão vazios e sem colunas de domínio — quem cria as colunas
  (Login/Senha/Link em Acessos, Tipo/Status no Controle etc.): nós via API ou o time no app?
- As automações internas (Jan/Luciano, Controle→Contratos) já existem no Sunday ou serão
  recriadas por nós?
- O cutover será por tema (contratos, jurídico, procon, acessos) ou tudo de uma vez?
