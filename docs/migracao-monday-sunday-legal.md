# Migração Monday → Sunday (temas de Legal) — plano estrutural

> **Status: Fase 0 (descoberta) executada, incluindo validação autenticada real contra a
> API do Sunday** (2026-08-10, segunda sessão, secrets `SUNDAY_API_TOKEN`/`SUNDAY_API_URL`
> injetados na VM). Este documento estrutura a migração do workspace de Legal do Monday
> (`beauty4all.monday.com`, workspace `2334257`) para o Sunday
> (`https://sunday.b4a.ai/workspaces/22`). **Nenhum comportamento foi alterado**: nenhum
> código de integração foi modificado, nenhum dado foi migrado, nenhum quadro foi criado,
> alterado ou apagado (Monday e Sunday intactos — somente `GET`/`OPTIONS`/`HEAD` foram
> usados na sessão autenticada). O resultado da Fase 0 está na seção
> ["Resultado da Fase 0 - Sunday API"](#resultado-da-fase-0---sunday-api).

## 1. Objetivo e escopo

Migrar os quadros e as integrações de **Legal** que hoje vivem no Monday para o Sunday,
mantendo os agentes deste repositório (Procon, Jurídico, Contratos) funcionando sem
interrupção. Fora de escopo imediato: quadros de outros times no mesmo workspace e o board
**Acessos** (credenciais do Questor), que é uma dependência transversal tratada à parte
(seção 3.4).

## 2. O que já sabemos do Sunday (levantado em leitura, sem tocar em nada)

Descoberto por inspeção do frontend público (`https://sunday.b4a.ai`, SPA Angular):

- **API REST** (não GraphQL) em `[REDACTED]`
  (Cloud Run). O caminho `/api/graphql` do domínio do frontend é só fallback do SPA.
- **Autenticação de API**: header `X-Sunday-Token: <secret>`. Tokens pessoais são criados
  na página **Settings** do Sunday (`POST /auth/me/api-tokens`; o secret aparece uma única
  vez). Login humano é Google (`/auth/google`).
- **Superfície relevante da API** (rotas observadas no bundle):
  - Workspaces: `GET /workspaces`, `/workspaces/mine`, `/workspaces/{id}/boards`,
    `/workspaces/{id}/members`.
  - Boards: `GET/POST /boards`, `/boards/{id}/columns` (+ `reorder`), `/boards/{id}/groups`
    (+ `reorder`), `/boards/{id}/items` (+ `reorder`), `/boards/{id}/members`,
    `/boards/{id}/views`, `/boards/{id}/links`, `/boards/{id}/mirror-values`,
    `/boards/{id}/archive|unarchive`, `/boards/{id}/capabilities`.
  - Itens: `PATCH /boards/items/{id}` (e `/status`, `/group`), valores de coluna em
    `POST /boards/items/{id}/values` e `PATCH /boards/items/{id}/values/{columnId}`,
    comentários em `/boards/items/{id}/comments`, anexos em
    `/boards/items/{id}/attachments/file` e `/attachments/link`, aprovação
    (`/approval/submit|approve|reject`), delegação, `push-forward`.
  - Busca: `GET /boards/search` (texto, retorna board/item/snippet).
  - Automações: `GET/POST /boards/{id}/automations`, `PATCH/DELETE /automations/{id}`,
    `GET /automations/{id}/runs`.
- **Gap identificado: não há webhook de saída** na superfície observada (nenhuma rota
  `/webhooks`). O Monday hoje chama nosso Cloud Run (`contratos-webhook serve-monday`)
  quando um item é criado no Controle. No Sunday, o equivalente terá de ser **polling**,
  **automação nativa do Sunday** ou um endpoint novo no Sunday — decisão em aberto (seção 5).

## 3. Inventário do que depende do Monday hoje (por domínio)

### 3.1 Procon (`src/classificacao_procons/monday/`)

| Uso | Onde | Detalhe |
|---|---|---|
| Board **procons** | `monday/client.py` | resolvido por nome (`MONDAY_BOARD_NAME`, default `procons`) ou `MONDAY_BOARD_ID`; grupo "pendentes de resposta" |
| Criar item + colunas | `register_complaint` | `create_item` + `change_multiple_column_values` coluna a coluna |
| Dedup | `_find_existing_item_id` | `items_page_by_column_values` por protocolo e por CPF |
| Upload de PDF | `upload_file_to_column` | API de arquivos do Monday (`add_file_to_column`) |
| Timeline | `create_item_update` | updates no item |
| Resposta elaborada | `update_elaborated_response_links` | colunas de link (Resposta Completa / Resumo / PDF Unificado) |
| PA (processo administrativo) | `update_administrative_process`, `pa_standalone_registry.py`, `pa_cip_links.py` | atualiza item existente, prazo interno +5 dias |

### 3.2 Jurídico (`src/classificacao_procons/juridico/`)

| Board (Monday) | Resolução | Uso |
|---|---|---|
| **prazos** (grupo "prazos processos") | nome ou `MONDAY_JURIDICO_BOARD_ID` | itens de providência por intimação (`juridico/monday.py`) |
| **audiencias** | nome ou `MONDAY_AUDIENCIAS_BOARD_ID` | itens de audiência |
| **processos judiciais** (quadro-mestre) | nome ou `MONDAY_PROCESSOS_BOARD_ID` | caso por CNJ; citação nova cria caso (`juridico/casos.py`) |
| **processos trabalhista** | nome ou `MONDAY_TRABALHISTA_BOARD_ID` | busca de caso trabalhista por CNJ |
| **kpi - processos consumidores** | nome ou `MONDAY_KPI_BOARD_ID` | marcos de estágio (acordo/encerramento) |

Recursos do Monday usados aqui que precisam de equivalente: **conexão de quadros**
(`board_relation`, vincula prazo/audiência ao caso-mestre), updates na timeline do caso,
mudança de Status/Decisão, e a **automação nativa do Monday** que alimenta o quadro de
audiências a partir do quadro-mestre.

### 3.3 Contratos (`src/classificacao_procons/contratos/`)

- Boards fixos por ID em `constants.py`: **Controle Assinaturas** `5301515799` e
  **Contratos** `5385471914`.
- Duas filas por documento (grupos **Jan** e **Luciano**), coluna **Quem Assina**, coluna
  **Tipo** só na fila Jan (dispara automação Monday → quadro Contratos quando **Assinado**).
- **Webhook do Monday** (`monday_webhook.py` + `webhook_cli.py serve-monday`, rota
  `/webhooks/monday`, com challenge) reage a item criado no Controle.
- Sync/reconcile/dedup pesados: `controle_sync.py`, `controle_reconcile.py`,
  `controle_dedup.py`, `controle_track_repair.py`, `parent_resolver.py` (resolve item pai
  no board Contratos por conexão de quadros), links por **Autentique ID** no corpo do item.
- Automações GitHub: cron horário e pós-merge (`contratos-sync-controle.yml`,
  `contratos-sync-after-agent-merge.yml`, `contratos-catch-up.yml` etc.).

Este é o domínio mais crítico e o único com **entrada** de eventos vindos do Monday.

### 3.4 Dependências transversais (mesmo token, fora do tema "legal")

- **Credenciais Questor**: board **Acessos** `7591024769` (`credentials/monday_board.py`),
  lido por `questor-daily.yml`. **Decisão (2026-08-10): fora do escopo desta migração.**
  A futura migração dessas credenciais para o **Secret Manager** é projeto separado.
  Senhas/segredos **não** serão copiados do Monday para o Sunday em hipótese alguma.
- **Workflows GitHub com `MONDAY_API_TOKEN`** (15): `procon-hourly`, `procon-sla-watchdog`,
  `procon-proconsumidor-local`, `juridico-hourly`, `questor-daily`, `jan-luciano-audit`,
  `controle-exclusion-analysis`, `agent-pr-automerge` e os 8 `contratos-*`.
- **Estado local/dedup** que referencia IDs do Monday: `data/questor-alerted.json` não, mas
  os arquivos de estado do contratos-sync e os links Autentique↔Controle guardam **item IDs
  do Monday** — na migração os IDs mudam, então é preciso uma **tabela de correspondência**
  `monday_item_id → sunday_item_id` (seção 7, Fase 2).

## 4. Mapeamento funcional Monday → Sunday

| Capacidade usada hoje (Monday GraphQL) | Equivalente Sunday (REST) | Confiança |
|---|---|---|
| `create_item(board, group, name)` | `POST /boards/{id}/items` | alta |
| `change_multiple_column_values` | `POST /boards/items/{id}/values` / `PATCH .../values/{col}` | alta |
| `items_page_by_column_values` (dedup por protocolo/CPF/CNJ) | `GET /boards/{id}/items` + filtro client-side, ou `GET /boards/search` | média (verificar filtros server-side) |
| `create_update` (timeline) | `POST /boards/items/{id}/comments` | alta |
| `add_file_to_column` (PDF) | `POST /boards/items/{id}/attachments/file` | alta |
| Colunas de link | `attachments/link` ou coluna própria de link | média (verificar tipos de coluna) |
| `board_relation` (conexão de quadros) | `/boards/{id}/links` + `/mirror-values` | média (semântica a confirmar) |
| Automação Monday (Tipo→Contratos; mestre→audiências) | `POST /boards/{id}/automations` | média (catálogo de gatilhos/ações a confirmar) |
| Webhook de item criado (Controle) | **sem equivalente visível** → polling, automação ou feature nova | baixa — decisão em aberto |
| Status/labels (`status` column settings) | coluna de status Sunday + `PATCH /boards/items/{id}/status` | alta |
| URL do item (`https://<slug>.monday.com/boards/{b}/pulses/{i}`) | `https://sunday.b4a.ai/workspaces/22/boards/{b}?item={i}` (formato a confirmar) | média |

## 5. Decisões (fechadas em 2026-08-10; detalhes técnicos na seção da Fase 0)

1. **Eventos de saída**: **polling** como arquitetura inicial, partindo do cron
   `contratos-sync-controle`. A Fase 0 confirmou que automações do Sunday têm ação
   `webhook` (chamada HTTP externa) com campo de URL; método/headers/retries/timeout não
   são observáveis pelo frontend e ficam pendentes de verificação autenticada (seção da
   Fase 0). Nada muda em produção por ora.
2. **Token de serviço**: Fase 0 usa os secrets `SUNDAY_API_TOKEN` + `SUNDAY_API_URL` já
   cadastrados. Antes do cutover, será emitido token por conta de serviço dedicada B4A.
   *Nota operacional (atualizada 2026-08-10, 2ª sessão): os dois secrets foram injetados
   nesta VM nova e a parte autenticada e de leitura da descoberta foi executada com
   sucesso — ver F0.11. O token atual é pessoal (do Gerente Jurídico, usuário id `37`),
   não uma conta de serviço; e tem escopo restrito (ver F0.1/F0.2): funciona para
   dados (boards/itens/valores/comentários/anexos/automações) mas é **rejeitado com 403**
   em rotas de "configuração" (`/boards/{id}/links`, `/boards/{id}/views`,
   `/boards/{id}/mirror-values`, `/auth/me/api-tokens`, busca `/boards/search`), que
   exigem sessão de login (JWT) ou escopo de token específico ausente. Confirma-se a
   necessidade de conta de serviço com escopo maior antes do cutover.*
3. **Tipos de coluna**: catálogo completo confirmado via bundle do frontend (23 tipos) —
   ver seção da Fase 0. Payloads por tipo confirmados na fonte do SPA; validação final por
   leitura autenticada de um board real.
4. **Automações nativas**: catálogo mapeado (8 gatilhos, 14 ações). A ação `create_item`
   **não** tem seletor de board de destino (cria no mesmo board) → as automações A e B
   (Assinado→Contratos; mestre→audiências) **não** têm equivalente nativo cross-board e
   passam para o nosso código (ou gatilho + ação `webhook` para nosso serviço).
5. **Histórico**: migrar **itens não concluídos/abertos + últimos 12 meses** (itens,
   values, updates/comentários, anexos, relações, com mapa de IDs Monday→Sunday). Monday
   permanece em modo leitura por período de segurança após o cutover. Volumes na Fase 0.
6. **Board Acessos** (`7591024769`): **fora do escopo**. Credenciais → Secret Manager em
   projeto separado. Nunca copiar segredos do Monday para o Sunday.

## 6. Arquitetura proposta no código (quando formos implementar)

- Novo pacote `src/classificacao_procons/sunday/` com `client.py` espelhando a interface
  pública do `monday/client.py` (mesmas assinaturas de alto nível: `register_complaint`,
  `find_item_id_by_protocol`, `create_item_update`, upload etc.), para que os pipelines não
  mudem.
- **Seletor de backend por domínio** via env (ex.: `LEGAL_TRACKER_BACKEND=monday|sunday|dual`),
  permitindo cutover independente para Procon, Jurídico e Contratos. O modo `dual`
  (escreve nos dois, lê do Monday) serve para o período de sombra.
- Envs novas: `SUNDAY_API_TOKEN`, `SUNDAY_API_BASE_URL`, `SUNDAY_WORKSPACE_ID=22` e
  `SUNDAY_*_BOARD_ID` por quadro (mesma convenção dos `MONDAY_*_BOARD_ID`).
- Scripts one-shot em `scripts/` (fora do pacote): inventário do Monday (read-only),
  criação de estrutura no Sunday (idempotente) e migração de dados com tabela de
  correspondência em `data/monday-sunday-map.json`.

## 7. Fases

### Fase 0 — Descoberta e congelamento de esquema (read-only, sem risco)

1. Emitir token do Sunday (conta de serviço) e validar a API: `GET /workspaces/mine`,
   `GET /workspaces/22/boards`, criação de board de teste em workspace sandbox.
2. Rodar inventário read-only do Monday (workspace 2334257): boards, grupos, colunas com
   `settings_str`, automações e volume de itens por board. Salvar snapshot JSON versionado
   (sem dados pessoais — só esquema + contagens).
3. Responder as decisões da seção 5 com base no que a API do Sunday realmente suporta.
4. Congelar o esquema dos quadros de Legal no Monday (sem novas colunas durante a migração).

### Fase 1 — Estrutura no Sunday (cria quadros vazios, não toca no Monday)

1. Criar no workspace 22 os quadros equivalentes: `procons`, `prazos`, `audiencias`,
   `processos judiciais`, `processos trabalhista`, `kpi - processos consumidores`,
   `Controle Assinaturas`, `Contratos` — com grupos e colunas mapeados da Fase 0.
2. Recriar automações (Tipo→Contratos; mestre→audiências) ou registrar que passam ao código.
3. Validação manual do time de Legal na UI do Sunday (nomes, colunas, visões).

### Fase 2 — Migração de dados

1. Script idempotente Monday→Sunday por board: itens (+ grupo, colunas), updates→comments,
   anexos→attachments, respeitando o recorte de histórico decidido (seção 5.5).
2. Gerar `data/monday-sunday-map.json` (`board_id`/`item_id` antigos → novos) e regravar as
   chaves de estado que apontam para itens Monday (links Autentique↔Controle inclusive).
3. Dry-run completo + relatório de divergências antes da carga real; carga em board por board.

### Fase 3 — Adaptação do código e período de sombra

1. Implementar `sunday/client.py` + seletor de backend (seção 6), com testes unitários
   mockando a API (mesmo padrão dos testes atuais do Monday).
2. Rodar em modo `dual`/dry-run por alguns ciclos dos crons (`procon-hourly`,
   `juridico-hourly`, `contratos-sync-controle`) comparando resultados Monday × Sunday.

### Fase 4 — Cutover por domínio (ordem do menor para o maior risco)

1. **KPI / leitura** → 2. **Prazos + Audiências** → 3. **Procon** → 4. **Contratos**
   (por último: é o domínio com webhook de entrada, automação e mais estado acumulado).
2. Em cada cutover: trocar env/secret nos workflows, monitorar 1 semana, manter o board
   Monday correspondente como somente leitura (renomear com prefixo `[MIGRADO]`).

### Fase 5 — Descomissionamento

1. Remover código Monday dos domínios migrados, secrets `MONDAY_*` dos workflows de Legal,
   atualizar `AGENTS.md`/docs. Arquivar os boards no Monday.

## 8. Riscos principais

| Risco | Mitigação |
|---|---|
| Sunday sem webhook de saída quebra o fluxo do Controle | decidir na Fase 0; fallback: polling no cron horário já existente |
| IDs novos invalidam estado/dedup acumulado | tabela de correspondência + regravação de estado na Fase 2 |
| Automações nativas sem equivalente | mover regra para o nosso código (já temos sync que sabe reparar filas Jan/Luciano) |
| Dois sistemas ativos durante a sombra → dados divergem | Monday permanece fonte da verdade até o cutover do domínio; modo `dual` só escreve espelho |
| Token pessoal revogado ao desligar a conta do emissor | emitir por conta de serviço dedicada (decisão 5.2) |
| API do Sunday é interna e pode mudar | fixar contrato na Fase 0 com o time do Sunday; testes de contrato no CI |

## 9. Checklist de validação (cada fase)

- `ruff check src tests` e `pytest` verdes (validação obrigatória do repositório).
- Dry-run de cada script com relatório revisado por humano antes de executar de verdade.
- Após cada cutover: um ciclo completo do cron do domínio sem erro + conferência amostral
  de 10 itens no Sunday contra o Monday.

## 10. O que explicitamente NÃO muda agora

- Nenhum board, item ou automação foi criado/alterado no Monday ou no Sunday.
- Nenhum código de integração foi alterado; `MONDAY_API_TOKEN` e workflows seguem como estão.
- Este documento é o único artefato desta etapa.

---

## Resultado da Fase 0 - Sunday API

> Executada em duas sessões, **sempre somente leitura** (`GET`/`OPTIONS`/`HEAD`, nunca
> `POST`/`PATCH`/`PUT`/`DELETE`). Fontes: (a) inspeção do bundle público do SPA
> (`https://sunday.b4a.ai`, Angular, 36 arquivos JS — serviços HTTP minificados mas com
> rotas e payloads literais); (b) sondagens não autenticadas na API; (c) inventário
> read-only do Monday via `MONDAY_API_TOKEN`; (d) **2026-08-10, 2ª sessão** — validação
> autenticada real contra a API do Sunday com `SUNDAY_API_TOKEN`/`SUNDAY_API_URL` (VM nova
> com os secrets injetados), cobrindo autenticação, identidade/permissões, o workspace 22
> real e seus boards/grupos/colunas/itens/valores/comentários/anexos/automações — ver
> F0.11 para o resultado consolidado (o que confirma, corrige e o que ainda depende de
> escrita). Nada foi inventado: o que não pôde ser confirmado está marcado como
> **pendente**.

### F0.1 Plataforma e autenticação (confirmado)

- API REST em `[REDACTED]` (Cloud Run; Express/
  NestJS — header `x-powered-by: Express`, erros no formato Nest).
- Header de autenticação de API: **`X-Sunday-Token: <secret>`** (frontend usa
  `Authorization: Bearer <JWT>` para sessões humanas; tokens de API são criados em
  Settings via `POST /auth/me/api-tokens` — o secret é exibido uma única vez).
- Erros JSON padronizados: `{"message":"Unauthorized","statusCode":401}`;
  `{"message":"Cannot GET /x","error":"Not Found","statusCode":404}`. O frontend lê
  `error.message` para exibir falhas de validação.
- CORS: `access-control-allow-methods: GET,HEAD,PUT,PATCH,POST,DELETE` (origem restrita a
  `https://sunday.b4a.ai`; irrelevante para chamadas server-to-server; a resposta de
  `OPTIONS` é uma política CORS genérica, **não** reflete os métodos de fato suportados
  pela rota específica — confirmado em 2026-08-10 comparando `OPTIONS /boards/{id}/items`
  e `OPTIONS /boards/items/{id}/values`, que devolveram o mesmo `Allow` genérico).
- `GET /health` → 200 sem auth (`{"status":"ok","service":"sunday-api","uptime":<segundos>}`)
  — **confirmado em 2026-08-10** contra a API real.
- Sem o header (ou com token inválido), `GET /auth/me` → `401
  {"message":"Unauthorized","statusCode":401}` — **confirmado**.
- 404 de recurso inexistente tem mensagem de domínio, não só o genérico do Nest: `GET
  /boards/999999` → `404 {"message":"Board not found.","error":"Not Found",
  "statusCode":404}` (o genérico `{"message":"Cannot GET /x", ...}` aparece só quando a
  *rota* não existe, não quando o *recurso* não existe) — **confirmado**.

**Identidade/permissões do token (F0.11, confirmado 2026-08-10):** `GET /auth/me` é o
endpoint de introspecção — responde com o token `X-Sunday-Token` válido e devolve o
perfil completo do usuário dono do token: `id`, `email`, `name`, `job_title`,
`access_level` (`"contributor"` para o token usado nesta sessão), `admin_scopes` (`[]`
— vazio), `hierarchy_level`/`hierarchy_label`, `team_id`, `manager_user_id`,
`business_unit`, `sunday_enabled`, `last_login_at`. **Não há endpoint dedicado só a
"permissões"** — `access_level` + `admin_scopes` do próprio `/auth/me` são a informação de
autorização disponível; o papel por workspace/board vem embutido nas respostas de
`GET /workspaces/{id}` (`my_role`) e `GET /boards/{id}` (`members[].role`), não num
endpoint de introspecção separado.

**Correção importante — tokens de API têm escopo restrito, menor que a sessão do
navegador:** várias rotas que o bundle do SPA usa (logado via JWT humano) devolvem `403`
quando chamadas com `X-Sunday-Token` (token pessoal), mesmo para leitura:
- `GET /boards/{id}/links`, `GET /boards/{id}/views`, `GET /boards/{id}/mirror-values`,
  `GET /auth/me/api-tokens` → `403 {"message":"Este token de acesso não pode usar esta
  rota. Excluir ou alterar configurações exige login.","error":"Forbidden",
  "statusCode":403}` — rotas classificadas como "configuração" exigem sessão (JWT), não
  token de API.
- `GET /boards/search` → `403 {"message":"Este token não tem o escopo \"search\"
  necessário para esta ação.","error":"Forbidden","statusCode":403}` — revela que
  **tokens de API têm escopos nomeados individuais** (pelo menos `"search"` existe),
  distintos de `admin_scopes` do usuário. Isso **não estava documentado** na leitura do
  bundle (a UI não expõe granularidade de escopo por token).
- `GET /workspaces/orphan-boards` → `403 {"message":"Apenas administradores podem
  gerenciar workspaces.","error":"Forbidden","statusCode":403}` — este é um 403 de
  **papel** (o usuário não é admin de workspace), não de escopo de token; comportamento
  esperado dado `access_level: "contributor"`.
- Rotas de dados seguem funcionando normalmente com o token pessoal: boards, columns,
  groups, items, values, comments, attachments e automations (listagem) — **todas
  confirmadas com `200`** nesta sessão.

**Implicação para a Fase 1**: a conta de serviço dedicada (decisão §5.2) precisa ter, além
do token, os **escopos certos** habilitados (ex.: `search`, se formos depender dele) e
avaliar se operações de configuração (criar/editar `links`/`views`/`mirror-values`,
automações) vão precisar de um caminho de sessão (login) em vez do token de API simples —
isso não estava nas incógnitas originais e é um risco novo para o Fase 1/2 (criação de
estrutura e `board_relation`/mirror entre boards).

### F0.2 Endpoints confirmados (extraídos dos services do SPA)

**Workspaces** (`/workspaces`): `GET /` (`?include_archived=true`), `GET /mine`,
`GET/PATCH /menu-config`, `GET /orphan-boards`, `GET/PATCH/DELETE /{id}`,
`GET /for-board/{boardId}`, `POST /` , `POST /{id}/boards` (`{board_id}`),
`DELETE /{id}/boards/{boardId}`, `PATCH /{id}/boards/reorder` (`{board_ids}`),
`POST /{id}/members` (`{user_id, role}` — default `"member"`),
`PATCH /{id}/members/{userId}/role`, `DELETE /{id}/members/{userId}`,
`GET/PUT /{id}/context-doc`.
**Correções confirmadas em 2026-08-10**: `GET /workspaces` só lista os workspaces em que
o dono do token participa (não é um índice global — confirmado, devolveu só o workspace
`22` para este token); `GET /workspaces/22/menu-config` → `404 Cannot GET` (rota de
leitura não existe nesse formato; talvez só `PATCH`, não testado por ser escrita);
`GET /workspaces/orphan-boards` → `403 "Apenas administradores podem gerenciar
workspaces."` (exige admin de workspace, não é o caso do token atual —
`access_level: "contributor"`); `GET /workspaces/22/context-doc` → `200` (funciona com o
token, corpo vazio neste workspace); não existe `GET /workspaces/{id}/members` dedicado —
a lista de membros vem embutida em `GET /workspaces/{id}` → campo `members[]`.

**Boards** (`/boards`): `GET /` (`?template=`, `?archived=true`), `POST /`
(`{name, description?, template_key, area_options?, workspace_id}`), `GET/PATCH /{id}`,
`POST /{id}/archive|unarchive`, `PATCH /{id}/capabilities`, `GET/POST /{id}/members`,
`GET /search?q=&limit=` (retorna `{results:[{board_id, board_name, item_id, item_name,
snippet}...], total, capped}`), `GET /me/items`, `GET /me/approvals`, `GET /me/ratings`.
**Correções confirmadas em 2026-08-10 (leitura autenticada real)**:
`GET /boards/{id}/members` → `404 Cannot GET` (não existe; a lista de membros do board
vem embutida em `GET /boards/{id}` → campo `members[]`, não em endpoint próprio);
`GET /boards/search` → `403` (falta escopo `search` no token — ver F0.1); `GET
/boards/{id}/capabilities` → `404` (só existe `PATCH`, como já indicado — confirmado, sem
GET dedicado).

**Grupos**: `GET/POST /boards/{id}/groups` (`{name, color}`; cores fixas: neutral, amber,
blue, green, violet, pink…), `PATCH /boards/{id}/groups/reorder` (`{group_ids}`),
`PATCH/DELETE /boards/groups/{groupId}`.

**Colunas**: `GET/POST /boards/{id}/columns`, `PATCH/DELETE /boards/columns/{colId}`,
`PATCH /boards/{id}/columns/reorder` (`{column_ids}`). Payload de criação: `{label, type,
...}` + extras por tipo: `options: [{key:"opt_1", label, color}]` (status/status_multi/
dropdown), `expression` (formula), `source_board_id` + `source_column_id` (mirror),
`source_board_id` (board_relation).

**Itens**: `GET /boards/{id}/items` (lista completa — **sem paginação visível**),
`POST /boards/{id}/items` (`{name, area?, target_date?, parent_item_id?, group_id?}` —
subitens nativos via `parent_item_id`, profundidade controlada por `board.hierarchy_depth`),
`PATCH /boards/items/{id}` (campos de sistema: `name`, `area`, `target_date`,
`owner_user_id`…), `PATCH /boards/items/{id}/status` (`{status, cascade}`),
`PATCH /boards/items/{id}/group` (`{group_id}`), `PATCH /boards/{id}/items/reorder`,
`POST /boards/items/{id}/push-forward` (`{days}`), `DELETE /boards/items/{id}`.
O item tem **Status de sistema** (fora das colunas), definido por `board.status_set`
(`[{key, label, color, terminal}]`).

**Values**: `GET /boards/items/{id}/values` → `[{column_id, value}]` (o SPA faz **uma
chamada por item** — N+1; não há endpoint bulk visível), `PATCH
/boards/items/{id}/values/{columnId}` com corpo `{"value": <valor>}`.

**Comentários**: `GET/POST /boards/items/{id}/comments` (`{body, kind, mention_user_ids?}`;
`kind` observado: `"reply"` (default), `"approval"`, `"rejection"`),
`PATCH/DELETE /boards/comments/{commentId}`.

**Anexos**: `GET /boards/items/{id}/attachments`; upload binário `POST
/boards/items/{id}/attachments/file` (multipart, campo `file`); anexo por link `POST
/boards/items/{id}/attachments/link` (`{url, filename}`); `DELETE /boards/attachments/{id}`.

**Conexões/espelho**: `GET/POST /boards/{id}/links`, `DELETE /boards/links/{id}`;
`GET /boards/{id}/mirror-values?column_id=`.

**Automações**: `GET/POST /boards/{id}/automations`, `PATCH/DELETE /automations/{id}`,
`GET /automations/{id}/runs` (runs com `status` success/error/skipped + `detail` +
timestamp — há log de execução).

**Aprovação** (capability opcional por board): `POST /boards/items/{id}/approval/submit|
approve|reject`, `POST /boards/items/{id}/delegate`, `PATCH /boards/{id}/approvers`.

Outros módulos existentes (fora do nosso escopo): `/catalogs`, `/work-calendar`,
`/processes`, `/form-invites`, `/public/forms`, `/notifications`, `/users` (diretório/
admin), `/intranet/announcements`, `/bia/chat`.

### F0.3 Tipos de coluna confirmados (catálogo literal do SPA)

Essenciais: `text`, `long_text`, `number`, `status`, `status_multi`, `dropdown`, `date`,
`checkbox`. Detalhes: `people`, `timeline`, `rating`, `tags`, `link`, `file_link`
("Arquivo (link)"), `files` ("Arquivos (vários)" — um link por linha), `email`, `phone`.
Avançado: `dependency`, `board_relation` ("Conectar board"), `formula` (read-only),
`mirror` (read-only, segue a coluna Conectar). Automáticas (read-only): `creation_log`,
`last_updated`, `item_id`. Existe ainda `time_tracking` no runtime (renderização e
automações), mas **fora** do seletor de nova coluna.

### F0.4 Payload de `values` por tipo (confirmado na fonte do SPA)

| Tipo | Formato do `value` |
|---|---|
| text / long_text / email / phone / link | string |
| number / rating | número |
| date | string `YYYY-MM-DD` (o SPA usa `toISOString().slice(0,10)`) |
| timeline | `{start: "YYYY-MM-DD", end: "YYYY-MM-DD"}` |
| checkbox | booleano |
| status / dropdown | string = `key` da opção |
| status_multi | array de `keys` (aceita também `{keys:[...]}` na leitura) |
| people | string = `user_id` |
| board_relation / dependency | `{links: [{item_id, label}]}` (aceita `{item_id, label}` único na leitura) |
| files | string com um link por linha |
| formula / mirror / creation_log / last_updated / item_id | read-only (não gravar) |

Sem tipo "data e hora": `date` é só dia; horário de audiência precisará de convenção
(ex.: coluna `text` auxiliar ou horário no nome/comentário) — mesma limitação prática que
já contornamos no Monday com colunas `date` + hora no título.

### F0.5 Automações (catálogo literal do SPA)

Estrutura: `{title, enabled, trigger: {type, config}, conditions: [{column, op, value}],
actions: [{type, config}]}`; condições com ops `is, is_not, empty, not_empty, contains,
in_group`.

**Gatilhos (8)**: `column_changed` (config `{column, to?}`), `item_created`,
`approval_changed` (`{state}`), `date_arrives` (`{column}`), `date_offset`
(`{column, days, direction, unit}` — dias corridos ou úteis), `schedule`
(`{freq, weekdays}`), `people_assigned`, `group_changed`.

**Ações (14)**: `set_value` (`{column, value}`; aceita `"today"` para datas), `notify`
(`{to}`), `email` (`{to}`), `push_date` (`{column, days, direction, unit}`), `duplicate`
(`{with_subitems}`), `create_subitem` (`{name}`), `create_item` (`{name}` — **cria no
mesmo board; não há seletor de board de destino**), `move_group` (`{group}`), `archive`,
`update` (comentário, `{text}`), `assign` (`{mode: creator|owner}`), `start_timer`,
`stop_timer` (`{column}` time_tracking), **`webhook`** (`{url}`).

**Chamada HTTP externa: existe** (ação `webhook`, rótulo "Disparar webhook"). A UI expõe
**apenas o campo URL** (`{url: ""}`). Método HTTP, headers, autenticação, corpo do payload,
retries e timeout são implementados no backend e **não são observáveis pelo frontend** —
ficam **pendentes** de verificação autenticada (ler uma automação existente não basta;
requer teste controlado com endpoint de eco — ver F0.11). Qualquer um dos 8 gatilhos pode
disparar a ação, incluindo `item_created` e `column_changed` com filtro de valor.

### F0.6 Reprodução das automações A e B

- **A) "Status = Assinado → criar item no board Contratos"**: gatilho `column_changed`
  (`column: "status"`, `to: <key Assinado>`) existe, mas **nenhuma ação cria item em outro
  board** (`create_item` é local). **Não reproduzível nativamente.** Alternativas:
  (1) gatilho + ação `webhook` → nosso serviço cria o item via API; (2) polling (cron
  existente). 
- **B) "Novo item no quadro-mestre → criar audiência"**: gatilho `item_created` existe;
  mesma limitação de ação cross-board. Mesmas alternativas.
- Conclusão: **as duas regras passam para o nosso código**, com `webhook` como possível
  gatilho de baixa latência (pendente F0.5) e polling como base garantida.

### F0.7 Inventário Monday (read-only, workspace Legal 2334257)

33 quadros no workspace (inclui 10 quadros de subelementos). Os 8 integrados ao código:

| Board (id) | Itens | Criados ≤12m | Colunas relevantes |
|---|---|---|---|
| Procons (4944254220) | 457 | 193 | 23 col.: 10 status, 5 date, file (Notificação/Docs SAC), long_text CPF, text CIP/FA |
| Prazos (3961072966) | 878 | 173 | 11 col.: text Número Processo, date Data/Fatal, people, file, time_tracking, board_relation → Processos |
| Audiências (4443295406) | 120 | 41 | 17 col.: date, location, link, email, people, file, 2× board_relation → Processos Judiciais |
| Processos Judiciais (5343921475) | 155 | 33 | 36 col.: 12 status, 5 date, 8 numbers, 2 file, location, email, formula |
| Processos Trabalhista (4443297481) | 24 | 3 | 15 col.: status, text, location, numbers, formula |
| KPI - Processos Consumidores (5563754463) | 31 | 0 | 16 col.: 7 status, 2 date, 5 numbers |
| Controle Assinaturas (5301515799) | 1607 | 506 | 17 col.: status (Status/Priority/Quem Assina/Tipo), 3 date, link, long_text, time_tracking, 2× board_relation |
| Contratos (5385471914) | 1119 | 330 | 11 col.: status Empresa/Vigência, text CNPJ/Tipo, 2 date, file Contrato, long_text, people |

Total: ~4.391 itens nos 8 quadros; ~1.279 criados nos últimos 12 meses (recorte decidido:
abertos + 12 meses; contagem de updates/anexos será apurada no dry-run da Fase 2).

Censo de tipos de coluna nos 8 quadros × mapeamento para o Sunday:

| Monday (ocorrências) | Sunday | Observação |
|---|---|---|
| status (44) | `status` (coluna) ou Status de sistema | decidir por board: o Status de sistema tem `status_set` + automações |
| date (20) | `date` | sem hora |
| numbers (16) | `number` | ok |
| text (13) / long_text (9) | `text` / `long_text` | ok |
| file (8) | anexos do item (`attachments/file`) + coluna `file_link`/`files` | **não há coluna de upload**; binário vive no item |
| people (6) | `people` | 1 pessoa por coluna |
| subtasks (6) | subitens nativos (`parent_item_id`) | Monday usa boards `Subelementos de *` separados |
| board_relation (5) | `board_relation` | + `mirror` se precisar espelhar |
| location (3) | `text` | **sem equivalente**; degradar para texto |
| time_tracking (2) | `time_tracking` | existe no runtime; criação via API a confirmar |
| link (2) | `link` | ok |
| formula (2) | `formula` | expressão própria do Sunday; reescrever |
| email (2) | `email` | ok |

O workspace tem ainda ~15 quadros de Legal **fora do código** (Certidões — 1.995 itens,
Legal - to do's — 387, Marcas registradas, Seguros, Diligências Metajur, Exercício de
Direitos de Titulares, Lista de Atas/Acs, Pagamentos Escritórios Externos, Plataformas/
Políticas Legal Team, Solicitações Contratos, Status Processo Jan, PDIC, Novo Workflow).
**Decisão de escopo pendente**: migrá-los junto (só dados, sem integração) ou por ondas.
O board Acessos (74 itens) está **excluído** (decisão 6).

### F0.7-bis Inventário Sunday real (workspace 22, leitura autenticada 2026-08-10)

**Correção relevante ao plano**: o workspace `22` **não é um workspace exclusivo de
Legal** — chama-se `"Support - Finance, Legal, People"` (`GET /workspaces/22`, campo
`name`; slug `support`), é compartilhado entre Finance/Legal/People, tem `member_count: 5`
e o papel do token nele é `my_role: "member"` (não admin/dono do workspace). Hoje tem
**6 boards**, nenhum deles com o volume de itens do Monday (o mapeamento §7 segue com os
IDs Sunday **em aberto** — nenhum dos 8 boards do código foi de fato criado no Sunday
ainda, exceto um recorte parcial de Audiências):

| Board (id) | Nome | Itens | Grupos | Colunas | Observação |
|---|---|---|---|---|---|
| 70 | Weekly Support | 12 | 1 (`Itens`) | 5 (template default: name/status/owner/date/area) | genérico de Support, fora do domínio Legal |
| 72 | Legal - Audiências | 9 | 2 (`Itens`, `Audiencias Pendentes`) | 5 (template default, mesmas 5) | **tem dados reais** (nomes de partes, datas, área Consumidor/Trabalhista) mas só com as colunas padrão — falta Número de Processo, local, e-mail, link, `board_relation` → Processos Judiciais que o board real do Monday tem (F0.7) |
| 74 | Cronograma + Processos Finance | 166 | 9 | 7 (5 default + 2 custom: `teste` text, `mes` text) | board de **Finance**, não é do domínio Legal; citado aqui só porque está no mesmo workspace 22 |
| 77 | Legal - Controle de Assinaturas - Jan & Luciano | 0 | 1 (`Itens`) | 5 (template default) | **vazio** — placeholder criado em 2026-08-10, sem colunas Status/Priority/Quem Assina/Tipo/link/etc. do board real |
| 78 | Legal - Acessos | 0 | 1 (`Itens`) | 5 (template default) | **vazio** — placeholder criado em 2026-08-10; confirma que nenhuma credencial foi copiada (decisão §5.6 respeitada) |
| 79 | Legal - Seguros | 0 | 1 (`Itens`) | 5 (template default) | **vazio** — placeholder criado em 2026-08-10 |

Nenhum board chamado `Procons`, `Prazos`, `Processos Judiciais`, `Processos Trabalhista`,
`KPI - Processos Consumidores` ou `Contratos` existe no workspace 22 hoje. Nenhuma
automação existe em nenhum dos 6 boards (`GET /boards/{id}/automations` → `[]` nos 6).
Nenhum item amostrado (Audiências e Finance) tem comentários ou anexos
(`GET /boards/items/{id}/comments|attachments` → `[]`) — não foi possível confirmar o
formato real de comentário/anexo **preenchido** por leitura (só o formato vazio); shape
preenchido continua **pendente** (F0.11), precisaria de item real com conteúdo ou teste
de escrita em sandbox.

**Formato de IDs confirmado**: todos os IDs observados (`workspace.id`, `board.id`,
`group.id`, `column.id`, `item.id`, `value.id`, `user.id`) são **strings numéricas
sequenciais** (ex.: `"22"`, `"74"`, `"7386"`, `"10188"`), não UUID — resolve a pendência
"formato real dos IDs" do F0.8/F0.11.

**Paginação**: `GET /boards/74/items` (166 itens) ignora silenciosamente
`?page=&limit=&per_page=` e devolve a lista completa nas duas chamadas (com e sem os
parâmetros) — **confirma** a ausência de paginação já suposta em F0.8.

**Rate limit**: nenhum header `X-RateLimit-*`/`Retry-After` em nenhuma das ~50 chamadas
desta sessão (workspaces, boards, columns, groups, items, values, comments, attachments,
automations, health, auth/me, erros 401/403/404), nem `429` — **não há indício de rate
limit exposto em header** nas respostas lidas (não prova ausência de limite no backend,
só que não é comunicado nas respostas observadas).

### F0.8 Limitações encontradas

1. `GET /boards/{id}/items` retorna a lista completa (sem paginação visível). **Correção
   importante (confirmada em 2026-08-10 contra a API real, board 74 com colunas
   custom)**: a resposta de `GET /boards/{id}/items` já embute `custom_fields` — um
   objeto `{<column.key>: <valor>}` com o valor de **cada coluna não-sistema** do item
   (ex.: `{"mes": "Julho"}`). Ou seja, **não é preciso 1 request por item** para ler os
   valores das colunas custom em massa; o endpoint `GET /boards/items/{id}/values` (que
   devolve `[{id, item_id, column_id, value, updated_at, updated_by_user}]`, com metadado
   por valor) só é necessário se precisarmos do `value.id`/`updated_by_user`/histórico por
   valor, ou para preparar o `column_id` exato de um `PATCH` futuro. Isso **reduz** o risco
   de N+1 apontado antes: um sync do Controle (1.600 itens) pode ler nomes/status/datas/
   colunas custom em **1 request** (`GET /boards/77/items`) e só cair para N+1 se precisar
   do metadado fino de cada valor. Ainda assim, mantém-se cache/estado local no polling
   (delta de `updated_at`) por robustez e para reduzir carga.
2. Sem endpoint de webhook de assinatura (o inverso da ação `webhook` de automação): não
   há como registrar callback fora de automações.
3. `create_item` de automação não cruza boards (F0.6).
4. Busca server-side é textual (`/boards/search`), sem filtro por valor de coluna — o
   equivalente de `items_page_by_column_values` (dedup por protocolo/CPF/CNJ) terá de ser
   feito client-side sobre a lista de items+values, com cache local.
5. Coluna de arquivo é por link; binários entram como anexos do item (sem coluna).
6. Sem tipo location e sem data-com-hora.
7. Rate limits: **confirmado em 2026-08-10** que não aparecem em nenhum header das
   respostas lidas (ver F0.7-bis) — mas seguem **não identificáveis** enquanto limite
   numérico/janela, já que nada nas ~50 chamadas desta sessão chegou perto de disparar
   um eventual limite. Limite de tamanho de upload continua **pendente** (exige escrita —
   F0.11).
8. Formato dos IDs: **confirmado em 2026-08-10** — strings numéricas sequenciais (não
   UUID) em todas as entidades lidas (workspace/board/group/column/item/value/user), ver
   F0.7-bis. URL canônica de item na UI: **ainda pendente** (não observada nesta sessão;
   as respostas da API não incluem uma URL de item, só IDs — a URL do item na SPA
   provavelmente é construída no front, ex. algo como
   `https://sunday.b4a.ai/workspaces/22/boards/{board_id}?item={item_id}`, mas isso não
   foi confirmado por não termos acessado a UI nesta sessão).

### F0.9 Gaps em relação ao Monday (consolidado)

| Recurso Monday usado hoje | Situação no Sunday |
|---|---|
| Webhook de item criado (challenge) | Sem registro de webhook; usar ação `webhook` de automação (semântica pendente) ou polling |
| Automação cross-board (Assinado→Contratos; mestre→audiências) | Inexistente; vai para nosso código |
| `items_page_by_column_values` | Inexistente; filtro client-side |
| Coluna `file` com upload | Anexos por item + coluna de link |
| Coluna `location` | Degradar para `text` |
| `add_file_to_column` (PDF Procon) | `POST /boards/items/{id}/attachments/file` |
| Updates na timeline | `comments` (com menções) — equivalente direto |
| Conexão de quadros + espelho | `board_relation` + `mirror` — equivalente direto |
| Subitens (boards `Subelementos`) | Subitens nativos — modelo até mais simples |
| Grupos com cor | Equivalente (paleta fixa) |

### F0.10 Recomendação de arquitetura para Contratos

1. **Base garantida: polling** — evoluir o `contratos-sync-controle` (cron horário) para o
   backend Sunday, com cache local de items+values para reduzir o N+1 e detectar deltas
   (itens novos no Controle, mudanças de Status). É a mesma semântica do sync atual, que
   já sabe reparar filas Jan/Luciano e reconciliar com o Autentique.
2. **Latência baixa (opcional, após confirmar F0.5)**: automação por board no Sunday com
   gatilho `item_created`/`column_changed` e ação `webhook` apontando para o nosso
   endpoint no Cloud Run (novo path `/webhooks/sunday`), substituindo o `serve-monday`.
   Só adotar depois de confirmar método/payload/retries com teste de eco autorizado.
3. As regras cross-board (A e B) ficam no nosso código em qualquer cenário.
4. Nada muda em produção nesta fase.

### F0.11 Validação autenticada real — resultado (2026-08-10, 2ª sessão, VM nova)

Secrets `SUNDAY_API_TOKEN` e `SUNDAY_API_URL` **confirmados injetados** nesta VM
(`disponível` para os dois; valores nunca impressos/logados). Todas as chamadas abaixo
usaram só `GET`/`OPTIONS`, contra a API real (`$SUNDAY_API_URL`), sem nenhuma
escrita — nenhum board, item, coluna, grupo, automação ou dado foi criado, alterado ou
apagado no Sunday nem no Monday nesta sessão.

**Confirmado por leitura real (itens antes listados como "pendente"):**
- **Autenticação**: `X-Sunday-Token: <secret>` funciona (`GET /auth/me` → `200`); sem
  header ou com token inválido → `401 Unauthorized`. Erro de rota inexistente vs.
  recurso inexistente têm mensagens diferentes (F0.1).
- **Identidade/permissões do token**: `GET /auth/me` devolve o perfil completo do dono do
  token (é pessoal, do Gerente Jurídico — usuário id `37`), com `access_level:
  "contributor"` e `admin_scopes: []`. Não há endpoint de "permissões" separado; o papel
  por workspace/board vem em `my_role` (`GET /workspaces/{id}`) e `members[].role`
  (`GET /boards/{id}`) — ver F0.1.
- **Acesso ao workspace 22**: confirmado (`GET /workspaces/22` → `200`); nome real
  `"Support - Finance, Legal, People"` (compartilhado, não exclusivo de Legal),
  `board_count: 6`, `member_count: 5`, `my_role: "member"` para o token atual — ver
  F0.7-bis.
- **Boards existentes no workspace 22, IDs e nomes**: os 6 listados em F0.7-bis (`70`
  Weekly Support, `72` Legal - Audiências, `74` Cronograma + Processos Finance, `77`
  Legal - Controle de Assinaturas - Jan & Luciano, `78` Legal - Acessos, `79` Legal -
  Seguros). Nenhum dos 8 boards do código (Procons/Prazos/Audiências completo/Processos
  Judiciais/Trabalhista/KPI/Controle Assinaturas completo/Contratos) existe ainda com o
  esquema real — só placeholders/parciais.
- **Grupos, colunas e tipos reais das colunas**: lidos nos 6 boards (`GET
  /boards/{id}/groups` e `/columns`) — hoje só o template default (`name`/`status`/
  `owner`/`target_date`/`area`) + 2 colunas `text` custom no board de Finance; nenhum
  board tem ainda os tipos avançados do Monday (`board_relation`, `status_multi`,
  `file_link`, etc.) para validar o payload real desses tipos — ver F0.7-bis e pendências
  abaixo.
- **Itens e values**: lidos com sucesso; `GET /boards/{id}/items` já embute
  `custom_fields` por item (correção ao F0.8 #1); `GET /boards/items/{id}/values`
  confirmado no formato documentado (`[{id, item_id, column_id, value, updated_at,
  updated_by_user}]`).
- **Comentários e anexos**: endpoints funcionam (`200`), mas todo item amostrado (Audiências
  e Finance) devolveu lista vazia — **shape vazio confirmado**, shape preenchido
  continua pendente (nenhum item no workspace 22 tem comentário/anexo hoje).
- **Automações**: `GET /boards/{id}/automations` → `200 []` nos 6 boards — nenhuma
  automação existe hoje no workspace 22; shape persistido da ação `webhook` continua
  pendente (nada para ler).
- **Formato real dos IDs**: strings numéricas sequenciais em todas as entidades — ver
  F0.7-bis (não é UUID).
- **Paginação**: nenhuma — `?page=&limit=&per_page=` são ignorados, lista completa
  sempre devolvida (testado com 166 itens).
- **Rate limit**: nenhum header relacionado em ~50 chamadas; sem `429`.
- **Descoberta nova (não esperada)**: tokens de API têm **escopo restrito** — rotas de
  "configuração" (`links`, `views`, `mirror-values`, `api-tokens`) exigem sessão/login
  (`403`), e `/boards/search` exige um escopo `"search"` que este token não tem (`403`).
  Ver F0.1 para o detalhe e a implicação para a conta de serviço da Fase 1/2.

**Ainda exigem escrita (não executadas — sem autorização explícita para escrita; propor
board sandbox dedicado quando autorizado):**
1. **Ação `webhook` de automação**: criar board sandbox + automação `item_created` →
   `webhook` apontando para endpoint de eco nosso; criar 1 item; capturar método, headers,
   payload, retries e timeout reais. *Por que leitura não basta*: o comportamento HTTP da
   entrega é do backend e não aparece em nenhuma resposta de leitura, e nenhuma automação
   existe hoje no workspace 22 para ler.
2. **Validação de `values` por tipo**: criar no sandbox 1 coluna de cada tipo (incl.
   `board_relation`, `status_multi`, `file_link`, `mirror`, `time_tracking`) e gravar
   valores válidos/inválidos (formatos exatos de erro e coerção). *Leitura não basta*:
   confirmado agora que o workspace 22 **não tem** exemplares desses tipos preenchidos.
3. **Upload de anexo**: enviar 1 PDF pequeno ao sandbox para medir limite de tamanho e
   shape da resposta. *Leitura não basta*: nenhum anexo existe hoje para ler o shape
   preenchido.
4. **`board_relation` cross-workspace**: confirmar se a conexão exige boards no mesmo
   workspace.
5. **`time_tracking` via API**: confirmar se `POST /columns` aceita o tipo.
6. **Escopo de token / conta de serviço**: confirmar quais escopos uma conta de serviço
   dedicada (decisão §5.2) precisaria solicitar para cobrir `search`, `links`, `views`,
   `mirror-values` — ou decidir que a Fase 1/2 não depende dessas rotas (o plano client-side
   de filtro já cobre a falta de `search` por valor de coluna, F0.8 #4).

### F0.12 Segurança

- Nenhum segredo foi lido, copiado ou registrado em log nesta fase. O board Acessos não
  foi consultado além do nome/contagem no inventário de boards do workspace.
- As consultas ao Monday foram exclusivamente de leitura (boards, grupos, colunas,
  contagens e datas de criação de itens; nenhum conteúdo de item foi exportado).
- **2ª sessão (2026-08-10, validação autenticada real)**: `SUNDAY_API_TOKEN` e
  `SUNDAY_API_URL` foram usados só em memória (variáveis de ambiente da VM), nunca
  impressos/logados/commitados; o valor de `SUNDAY_API_URL` também é tratado como
  segredo neste ambiente (por isso continua como `[REDACTED]` neste documento, igual à
  1ª sessão). Só `GET`/`OPTIONS` foram usados — nenhuma escrita no Monday ou no Sunday.
  O board **Legal - Acessos** (id `78`) no Sunday está **vazio** (0 itens) — confirmado
  por leitura, sem necessidade de tocar em conteúdo de credencial. O board **Legal -
  Audiências** (id `72`) já tem dados reais (nomes de partes de processos) — lidos só
  para confirmar shape/estrutura; nenhum nome, e-mail ou dado pessoal foi copiado para
  este documento (descrições ficam em termos genéricos, ex. "nomes de partes").
