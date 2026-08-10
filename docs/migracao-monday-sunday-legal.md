# Migração Monday → Sunday (temas de Legal) — plano estrutural

> **Status: Fase 0 (descoberta) — leitura autenticada concluída.** Este documento estrutura
> a migração do workspace de Legal do Monday (`beauty4all.monday.com`, workspace `2334257`)
> para o Sunday (`https://sunday.b4a.ai/workspaces/22`). **Nenhum comportamento foi
> alterado**: nenhum código de integração foi modificado, nenhum dado foi migrado, nenhum
> quadro foi criado ou alterado (Monday e Sunday intactos; só GET/OPTIONS/HEAD na API).
> O resultado da Fase 0 está na seção
> ["Resultado da Fase 0 - Sunday API"](#resultado-da-fase-0---sunday-api), incluindo a
> validação autenticada (F0.13).

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
   cadastrados. **Confirmado em VM nova**: ambos foram injetados e a autenticação
   funcionou (ver F0.13). O token atual está vinculado a um usuário humano
   (`access_level=contributor`); antes do cutover, emitir token por conta de serviço
   dedicada B4A.
3. **Tipos de coluna**: catálogo completo confirmado via bundle do frontend (23 tipos) —
   ver seção da Fase 0. No workspace 22, a leitura autenticada observou na prática
   `text`, `status`, `people`, `date`, `dropdown` (demais tipos seguem pendentes de
   exemplares preenchidos ou sandbox — F0.11).
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

- Nenhum board, item ou automação foi criado/alterado no Monday ou no Sunday
  (apenas leituras autenticadas na API do Sunday).
- Nenhum código de integração foi alterado; `MONDAY_API_TOKEN` e workflows seguem como estão.
- `sunday/client.py` **não** foi implementado nesta etapa.
- Este documento é o único artefato desta etapa.

---

## Resultado da Fase 0 - Sunday API

> Executada em 2026-08-10, **somente leitura**. Fontes: (a) inspeção do bundle público do
> SPA (`https://sunday.b4a.ai`, Angular, 36 arquivos JS — serviços HTTP minificados mas com
> rotas e payloads literais); (b) sondagens não autenticadas na API; (c) inventário
> read-only do Monday via `MONDAY_API_TOKEN`; (d) **validação autenticada** com
> `SUNDAY_API_TOKEN` + `SUNDAY_API_URL` injetados em VM nova (apenas GET/OPTIONS/HEAD —
> ver F0.13). Nada foi inventado: o que ainda depende de escrita autorizada permanece
> marcado como **pendente** (F0.11).

### F0.1 Plataforma e autenticação (confirmado)

- API REST em Cloud Run (`SUNDAY_API_URL`; Express/NestJS — header `x-powered-by: Express`,
  erros no formato Nest). Host observado: `*.run.app` (us-central1).
- Header de autenticação de API: **`X-Sunday-Token: <secret>`** (**confirmado** — 200 em
  `/auth/me`). O mesmo secret também autenticou via `Authorization: Bearer <secret>`
  (200); sem header → 401 `{"message":"Unauthorized","statusCode":401}`. Frontend humano
  usa Bearer JWT de sessão; tokens de API são criados em Settings via
  `POST /auth/me/api-tokens` (listar/revogar via API token → 403, exige login).
- Erros JSON padronizados: `{"message":"Unauthorized","statusCode":401}`;
  `{"message":"Cannot GET /x","error":"Not Found","statusCode":404}`;
  `{"message":"...","error":"Forbidden","statusCode":403}`.
- CORS: `access-control-allow-methods: GET,HEAD,PUT,PATCH,POST,DELETE` (origem restrita a
  `https://sunday.b4a.ai`; irrelevante para chamadas server-to-server).
- `GET /health` → 200 sem auth; `HEAD /health` → 200.

### F0.2 Endpoints confirmados (extraídos dos services do SPA)

**Workspaces** (`/workspaces`): `GET /` (`?include_archived=true`), `GET /mine`,
`GET/PATCH /menu-config`, `GET /orphan-boards`, `GET/PATCH/DELETE /{id}`,
`GET /for-board/{boardId}`, `POST /` , `POST /{id}/boards` (`{board_id}`),
`DELETE /{id}/boards/{boardId}`, `PATCH /{id}/boards/reorder` (`{board_ids}`),
`POST /{id}/members` (`{user_id, role}` — default `"member"`),
`PATCH /{id}/members/{userId}/role`, `DELETE /{id}/members/{userId}`,
`GET/PUT /{id}/context-doc`.

**Boards** (`/boards`): `GET /` (`?template=`, `?archived=true`), `POST /`
(`{name, description?, template_key, area_options?, workspace_id}`), `GET/PATCH /{id}`,
`POST /{id}/archive|unarchive`, `PATCH /{id}/capabilities`, `GET/POST /{id}/members`,
`GET /search?q=&limit=` (retorna `{results:[{board_id, board_name, item_id, item_name,
snippet}...], total, capped}`), `GET /me/items`, `GET /me/approvals`, `GET /me/ratings`.

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

### F0.4 Payload de `values` por tipo (SPA + correções da API autenticada)

| Tipo | Formato do `value` | Observação autenticada (F0.13) |
|---|---|---|
| text / long_text / email / phone / link | string | **Confirmado** em `/values` para colunas `text` não-sistema |
| number / rating | número | pendente de exemplar preenchido |
| date | SPA grava `YYYY-MM-DD`; API lê ISO datetime | **Corrigido**: item.`target_date` vem como `2026-08-17T12:00:00.000Z` mesmo com `settings.include_time=false` |
| timeline | `{start: "YYYY-MM-DD", end: "YYYY-MM-DD"}` | pendente de exemplar |
| checkbox | booleano | pendente de exemplar |
| status / dropdown | string = `key` da opção (SPA) | **Parcial**: `status` no item usa key do `status_set` (`to_do`/`follow_up`/`done`); `area` (dropdown sistema) aceitou labels livres (`Consumidor`, `Trabalhista`) com `settings.options=[]` |
| status_multi | array de `keys` (aceita também `{keys:[...]}` na leitura) | pendente de exemplar |
| people | string = `user_id` | **Confirmado** como item.`owner_user_id` (numeric string); não aparece em `/values` |
| board_relation / dependency | `{links: [{item_id, label}]}` (aceita `{item_id, label}` único na leitura) | pendente de exemplar |
| files | string com um link por linha | pendente de exemplar |
| formula / mirror / creation_log / last_updated / item_id | read-only (não gravar) | pendente de exemplar |

**Modelo dual confirmado na API real:** colunas de sistema (`is_system=true`, keys
`name`/`status`/`owner`/`target_date`/`area`) vivem como **campos do item**
(`name`, `status`, `owner_user_id`, `target_date`, `area`). `GET /boards/items/{id}/values`
devolve só values de colunas custom (não-sistema), no shape
`{id, item_id, column_id, value, updated_at, updated_by_user}`. O item também espelha
texts custom em `custom_fields` (mapa `column.key → value`).

Coluna `date` de sistema tem `settings.include_time=false`, mas o valor lido inclui
timestamp (meio-dia UTC nos exemplos). Horário de audiência ainda precisará de convenção
explícita se a granularidade real for só dia.

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

### F0.8 Limitações encontradas

1. `GET /boards/{id}/items` retorna a lista completa (sem paginação visível) e values são
   lidos **por item** (N+1) — para 1.600 itens do Controle, um sync completo = ~1.600
   requests; reforça a necessidade de cache/estado local no polling.
   **Confirmado autenticado**: resposta é array nu; `?limit=1&offset=0` **não é honrado**
   (mesma lista completa).
2. Sem endpoint de webhook de assinatura (o inverso da ação `webhook` de automação): não
   há como registrar callback fora de automações.
3. `create_item` de automação não cruza boards (F0.6).
4. Busca server-side é textual (`/boards/search`), sem filtro por valor de coluna — o
   equivalente de `items_page_by_column_values` (dedup por protocolo/CPF/CNJ) terá de ser
   feito client-side sobre a lista de items+values, com cache local.
   **Confirmado autenticado**: o token atual recebe 403
   (`Este token não tem o escopo "search"`).
5. Coluna de arquivo é por link; binários entram como anexos do item (sem coluna).
6. Sem tipo location; `date` de sistema expõe ISO datetime na leitura, mas
   `include_time=false` (granularidade efetiva a validar na escrita).
7. Rate limits: **nenhum header** `X-RateLimit-*` / `Retry-After` / similar observado em
   dezenas de GETs autenticados. Limite de upload segue pendente de teste de escrita.
8. **IDs confirmados**: todos numéricos em string (`"22"`, `"77"`, `"428"`, `"7389"`…).
   Não há UUID. Atenção ao **dual ID** do vínculo workspace↔board (F0.13).
9. Restrições do token de API (além de search): `GET /boards/{id}/links` e
   `GET /auth/me/api-tokens` retornam 403
   ("Este token de acesso não pode usar esta rota. Excluir ou alterar configurações exige
   login."). `GET /boards/{id}/members` → 404 (membros vêm embutidos em `GET /boards/{id}`).

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

### F0.11 Pendências que exigem token e/ou teste de escrita autorizado

**Somente leitura — CONCLUÍDA na validação autenticada (F0.13):**
- [x] `GET /auth/me` (identidade do token), `GET /workspaces/mine` e `GET /workspaces/22`.
- [x] Ler boards existentes: IDs, board/columns/groups/items/values/comments/attachments,
  capabilities e `status_set`.
- [x] Listar automações: endpoints respondem 200, mas **nenhum board do workspace 22 tem
  automações** — shape persistido da ação `webhook` **não pôde ser observado** sem criar
  uma (segue na lista de escrita).

**Exigem escrita (não executar sem nova autorização; propor board sandbox dedicado):**
1. **Ação `webhook` de automação**: criar board sandbox + automação `item_created` →
   `webhook` apontando para endpoint de eco nosso; criar 1 item; capturar método, headers,
   payload, retries e timeout reais. *Por que leitura não basta*: zero automações
   existentes no workspace 22; o comportamento HTTP da entrega é do backend.
2. **Validação de `values`/campos por tipo**: criar no sandbox 1 coluna de cada tipo
   (incl. `long_text`, `number`, `status` não-sistema, `board_relation`, `files`,
   `timeline`, etc.) e gravar valores válidos/inválidos. *Leitura não basta*: no workspace
   22 só há exemplares preenchidos de `text` (via `/values`) e dos campos de sistema
   `status`/`owner`/`target_date`/`area`.
3. **Upload de anexo**: enviar 1 PDF pequeno ao sandbox para medir limite de tamanho e
   shape da resposta (endpoints de leitura devolvem `[]` — sem exemplares).
4. **`board_relation` cross-workspace**: confirmar se a conexão exige boards no mesmo
   workspace. *Nota*: `GET /boards/{id}/links` está bloqueado para o token de API atual.
5. **`time_tracking` via API**: confirmar se `POST /columns` aceita o tipo.
6. **Escrita nos campos de sistema**: confirmar se `status`/`owner_user_id`/`target_date`/
   `area` atualizam via `PATCH /boards/items/{id}` (campos do item) e/ou via
   `PATCH .../values/{columnId}` — a leitura sugere o primeiro caminho.
7. **Comentários**: criar 1 comment para validar `kind` (`reply`/`approval`/`rejection`) e
   shape da resposta (leitura só viu `[]`).

### F0.12 Segurança

- Nenhum segredo foi impresso, ecoado ou commitado. Artefatos locais de exploração ficaram
  em `/tmp` (fora do repositório) e tiveram valores de token redigidos.
- O board **Legal - Acessos** (`78`) foi listado (nome/colunas/grupos/itens vazios) — **sem
  leitura de segredos** (board vazio; decisão 6 mantém Acessos fora do escopo de migração).
- As consultas ao Monday (fase anterior) e ao Sunday (esta VM) foram exclusivamente
  read-only (GET/OPTIONS/HEAD). Nenhum POST/PATCH/PUT/DELETE.

### F0.13 Validação autenticada (VM nova, 2026-08-10)

Secrets `SUNDAY_API_TOKEN` e `SUNDAY_API_URL` **disponíveis e funcionais**. Operações:
apenas GET/OPTIONS/HEAD.

#### Autenticação e identidade

| Checagem | Resultado |
|---|---|
| `GET /health` | 200 |
| `GET /auth/me` com `X-Sunday-Token` | 200 |
| `GET /auth/me` com `Authorization: Bearer` (mesmo secret) | 200 |
| Sem auth | 401 Unauthorized |
| Identidade | usuário humano `id="37"`, `access_level="contributor"`, `user_type="employee"`, `sunday_enabled=true`, `admin_scopes=[]` |
| Papel no workspace 22 | `my_role="member"` (também listado em `members`) |
| `GET /users/me` | 403 (requer admin) |
| `GET /auth/me/api-tokens` | 403 (API token não gerencia tokens) |

#### Workspace 22

- Nome: **Support - Finance, Legal, People** (`slug=support`, `business_unit=shared`).
- `board_count=6`, `member_count=5`.
- É o **único** workspace retornado por `GET /workspaces` e `GET /workspaces/mine` para
  este token.

#### Boards do workspace 22 (IDs reais)

| Board ID | Nome | Itens | Grupos | Notas |
|---|---|---|---|---|
| `70` | Weekly Support | 12 | 1 (`Itens`) | fora do escopo Legal |
| `72` | Legal - Audiências | 9 | 2 (`Itens`, `Audiencias Pendentes`) | esqueleto; colunas default |
| `74` | Cronograma + Processos Finance | 166 | 9 | board Finance com dados reais (útil como exemplar) |
| `77` | Legal - Controle de Assinaturas - Jan & Luciano | 0 | 1 (`Itens`) | **vazio**; ainda sem colunas do Monday |
| `78` | Legal - Acessos | 0 | 1 (`Itens`) | vazio; fora do escopo de migração |
| `79` | Legal - Seguros | 0 | 1 (`Itens`) | fora do código atual |

**Ainda não existem** no workspace 22 os equivalentes de: Contratos, Procons, Prazos,
Processos Judiciais, Processos Trabalhista, KPI.

**Dual ID (correção importante):** em `GET /workspaces/22`, cada entrada de `boards[]` tem
`id` = ID do **vínculo** workspace↔board e `board_id` = ID real do board. Usar o vínculo
em `/boards/{id}` → 403 "Sem permissão para ver esta board.". Em `GET /workspaces/mine`,
`boards[].id` já é o board real. De-para rápido: vínculo `66` → board `77` (Controle),
`59`→`72` (Audiências), `67`→`78` (Acessos).

#### Shapes observados

- **IDs**: numeric string em board/group/column/item/value/workspace/user/member.
- **Board**: `status_set` padrão `to_do` / `follow_up` / `done`; `capabilities` com
  `subitems/approvals/time_tracking/process=false`, `calendar_anchor=true`;
  `hierarchy_depth=1`; `members` embutidos (`role`: owner/editor).
- **Colunas default** (boards legais vazios): `name`(text/sys), `status`(status/sys,
  `use_board_status_set`), `owner`(people/sys), `target_date`(date/sys,
  `include_time=false`), `area`(dropdown/sys, `options=[]`).
- **Grupos**: `{id, board_id, name, color, position, is_collapsed_default, ...}`; cor
  observada `neutral`.
- **Itens**: campos de sistema no próprio objeto (`status`, `owner_user_id`,
  `target_date`, `area`, `assignee_user_ids`, `custom_fields`, `parent_item_id`, …).
- **Values**: só colunas não-sistema; array de
  `{id, item_id, column_id, value, updated_at, updated_by_user}`.
- **Comments / attachments / automations**: endpoints 200 com `[]` em todos os boards
  amostrados (sem exemplares).
- **Paginação**: inexistente na prática (array completo; query `limit` ignorada).
- **Rate limit**: nenhum header informativo nas respostas.

#### Hipóteses confirmadas × corrigidas

| Hipótese (pré-auth) | Status |
|---|---|
| API REST + `X-Sunday-Token` | **Confirmada** |
| Erros Nest (`statusCode` 401/403/404) | **Confirmada** |
| `GET /boards/{id}/items` sem paginação | **Confirmada** (+ `limit` ignorado) |
| Values N+1 por item | **Confirmada** |
| IDs numéricos (não UUID) | **Confirmada** |
| `status_set` no board + Status de sistema | **Confirmada** |
| Catálogo de endpoints de leitura (groups/columns/items/values/comments/attachments/automations) | **Confirmada** (200) |
| date como `YYYY-MM-DD` na API | **Corrigida** — leitura devolve ISO datetime (`…T12:00:00.000Z`) |
| `/values` carrega todos os tipos | **Corrigida** — sistema fica no item; `/values` = custom |
| Rate limit headers | **Corrigida** — ausentes (pelo menos neste token/rota) |
| Automações com shape `webhook` legível | **Pendente** — zero automações no WS 22 |
| Boards legais já estruturados como no Monday | **Corrigida** — só esqueletos/vazios; faltam Contratos/Procons/Prazos/Processos/KPI |

#### De-para parcial (Sunday IDs levantados)

| Board (legal) | Monday ID | Sunday board ID | Estado no Sunday |
|---|---|---|---|
| Controle Assinaturas | `5301515799` | `77` | criado vazio (nome longo Jan & Luciano) |
| Audiências | por nome/env | `72` | 9 itens de amostra; colunas default |
| Acessos | `7591024769` | `78` | vazio; **fora do escopo** |
| Contratos | `5385471914` | _(não existe)_ | criar na Fase 1 |
| Procons / Prazos / Processos / KPI | por nome/env | _(não existem)_ | criar na Fase 1 |
