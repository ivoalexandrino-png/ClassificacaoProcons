# Migração Monday → Sunday (temas de Legal) — plano estrutural

> **Status: Fase 0 (descoberta) executada, incluindo a validação autenticada da API real
> do Sunday (2026-08-10, somente leitura).** Este documento estrutura a migração do
> workspace de Legal do Monday (`beauty4all.monday.com`, workspace `2334257`) para o Sunday
> (`https://sunday.b4a.ai/workspaces/22`). **Nenhum comportamento foi alterado**: nenhum
> código de integração foi modificado, nenhum dado foi migrado, nenhum quadro foi criado ou
> alterado (Monday e Sunday intactos). O resultado da Fase 0 está na seção
> ["Resultado da Fase 0 - Sunday API"](#resultado-da-fase-0---sunday-api); a validação
> autenticada está em F0.13.

## 1. Objetivo e escopo

Migrar os quadros e as integrações de **Legal** que hoje vivem no Monday para o Sunday,
mantendo os agentes deste repositório (Procon, Jurídico, Contratos) funcionando sem
interrupção. Fora de escopo imediato: quadros de outros times no mesmo workspace e o board
**Acessos** (credenciais do Questor), que é uma dependência transversal tratada à parte
(seção 3.4).

## 2. O que já sabemos do Sunday (levantado em leitura, sem tocar em nada)

Descoberto por inspeção do frontend público (`https://sunday.b4a.ai`, SPA Angular):

- **API REST** (não GraphQL) em `https://sunday-api-757613635701.us-central1.run.app`
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
| `items_page_by_column_values` (dedup por protocolo/CPF/CNJ) | `GET /boards/{id}/items` + filtro client-side (`/boards/search` é só textual e exige escopo `search` no token — F0.13) | alta (confirmado: sem filtro server-side) |
| `create_update` (timeline) | `POST /boards/items/{id}/comments` | alta |
| `add_file_to_column` (PDF) | `POST /boards/items/{id}/attachments/file` | alta |
| Colunas de link | `attachments/link` ou coluna própria de link | média (verificar tipos de coluna) |
| `board_relation` (conexão de quadros) | `/boards/{id}/links` + `/mirror-values` | baixa (403 para o token de API atual — F0.13; resolver escopo antes) |
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
   Na VM nova de 2026-08-10, ambos foram injetados e a descoberta autenticada foi
   concluída exclusivamente com `GET` e `OPTIONS` (F0.13). O token atual é **pessoal**
   (usuário Ivo, `access_level: contributor`) e os tokens do Sunday têm **escopos** (este
   não tem `search`, por exemplo) — a emissão do token de serviço precisa definir o
   conjunto de escopos, incluindo o que destravar `/boards/{id}/links`/`mirror-values`.
3. **Tipos de coluna**: catálogo completo confirmado via bundle do frontend (23 tipos) —
   ver seção da Fase 0. A API real confirmou cinco tipos presentes no workspace 22
   (`text`, `status`, `people`, `date`, `dropdown`); os demais ainda exigem exemplares
   reais ou teste de escrita em sandbox.
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

1. ✅ Validar a API com token (feito em 2026-08-10, F0.13: `GET /workspaces/mine`,
   `GET /workspaces/22`, boards/colunas/grupos/itens/values). Pendente: emitir token de
   **conta de serviço** com escopos adequados e criar board de teste em sandbox (escrita).
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

> Executada em 2026-08-10, **somente leitura**. Fontes: (a) inspeção do bundle público do
> SPA (`https://sunday.b4a.ai`, Angular, 36 arquivos JS — serviços HTTP minificados mas com
> rotas e payloads literais); (b) sondagens não autenticadas na API; (c) inventário
> read-only do Monday via `MONDAY_API_TOKEN`; (d) validação autenticada na API real do
> Sunday, com os secrets `SUNDAY_API_TOKEN`/`SUNDAY_API_URL` injetados na VM nova.
> Nenhum valor de secret foi impresso ou registrado. Nada foi inventado: o que não pôde
> ser confirmado está marcado como **pendente**.

### F0.1 Plataforma e autenticação (confirmado)

- API REST em `https://sunday-api-757613635701.us-central1.run.app` (Cloud Run; Express/
  NestJS — header `x-powered-by: Express`, erros no formato Nest).
- Header de autenticação de API: **`X-Sunday-Token: <secret>`** (frontend usa
  `Authorization: Bearer <JWT>` para sessões humanas; tokens de API são criados em
  Settings via `POST /auth/me/api-tokens` — o secret é exibido uma única vez).
- Erros JSON padronizados: `{"message":"Unauthorized","statusCode":401}`;
  `{"message":"Cannot GET /x","error":"Not Found","statusCode":404}`. O frontend lê
  `error.message` para exibir falhas de validação.
- CORS: `access-control-allow-methods: GET,HEAD,PUT,PATCH,POST,DELETE` (origem restrita a
  `https://sunday.b4a.ai`; irrelevante para chamadas server-to-server).
- `GET /health` → 200 sem auth.
- `GET /auth/me` → 200 com `X-Sunday-Token`. O token pertence a usuário ativo e habilitado
  no Sunday, com `access_level=contributor`, `user_type=employee` e `admin_scopes=[]`.

### F0.2 Endpoints confirmados (extraídos dos services do SPA)

**Workspaces** (`/workspaces`): `GET /` (`?include_archived=true`), `GET /mine`,
`GET/PATCH /menu-config`, `GET /orphan-boards`, `GET/PATCH/DELETE /{id}`,
`GET /for-board/{boardId}`, `POST /` , `POST /{id}/boards` (`{board_id}`),
`DELETE /{id}/boards/{boardId}`, `PATCH /{id}/boards/reorder` (`{board_ids}`),
`POST /{id}/members` (`{user_id, role}` — default `"member"`),
`PATCH /{id}/members/{userId}/role`, `DELETE /{id}/members/{userId}`,
`GET/PUT /{id}/context-doc`.

Na API real, `GET /workspaces/22` inclui os arrays `boards` e `members`; as rotas
`GET /workspaces/22/boards` e `GET /workspaces/22/members` retornaram 404. Em
`boards[]`, `id` é o ID do **vínculo workspace-board** e `board_id` é o ID que deve ser
usado nas rotas `/boards/{id}`. Confundir os dois produz 403.

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

~~Sem tipo "data e hora": `date` é só dia~~ — **corrigido na leitura autenticada
(F0.13)**: a coluna `date` tem setting `include_time` e o campo de sistema `target_date`
retorna ISO datetime completo (`2026-07-28T12:00:00.000Z`). O formato de **escrita** com
hora continua pendente de teste (F0.11).

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
2. Sem endpoint de webhook de assinatura (o inverso da ação `webhook` de automação): não
   há como registrar callback fora de automações.
3. `create_item` de automação não cruza boards (F0.6).
4. Busca server-side é textual (`/boards/search`), sem filtro por valor de coluna — o
   equivalente de `items_page_by_column_values` (dedup por protocolo/CPF/CNJ) terá de ser
   feito client-side sobre a lista de items+values, com cache local.
5. Coluna de arquivo é por link; binários entram como anexos do item (sem coluna).
6. Sem tipo location. ~~Sem data-com-hora~~ — corrigido: `date` tem `include_time` e
   `target_date` retorna ISO datetime (F0.13).
7. Nenhum header de rate limit foi retornado nas leituras autenticadas; isso não prova
   ausência de limite. Limites de upload continuam pendentes de teste de escrita.
8. IDs reais de workspace, board, vínculo, grupo, coluna, item e value são **strings
   numéricas decimais**, não UUIDs. A URL canônica de item continua pendente.

### F0.9 Gaps em relação ao Monday (consolidado)

| Recurso Monday usado hoje | Situação no Sunday |
|---|---|
| Webhook de item criado (challenge) | Sem registro de webhook; usar ação `webhook` de automação (semântica pendente) ou polling |
| Automação cross-board (Assinado→Contratos; mestre→audiências) | Inexistente; vai para nosso código |
| `items_page_by_column_values` | Inexistente; filtro client-side (`/boards/search` além de textual exige escopo `search` no token — F0.13) |
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

**Somente leitura concluída:** identidade e permissões do token; workspace 22; boards,
grupos, colunas, itens, values, comentários, anexos, automações, formato de IDs,
paginação aparente e headers de rate limit. Resultado detalhado em F0.13.

**Exigem escrita (não executar sem nova autorização; propor board sandbox dedicado):**
1. **Ação `webhook` de automação**: criar board sandbox + automação `item_created` →
   `webhook` apontando para endpoint de eco nosso; criar 1 item; capturar método, headers,
   payload, retries e timeout reais. *Por que leitura não basta*: o comportamento HTTP da
   entrega é do backend e não aparece em nenhuma resposta de leitura.
2. **Validação de `values` por tipo**: criar no sandbox 1 coluna de cada tipo e gravar
   valores válidos/inválidos (formatos exatos de erro e coerção). *Leitura não basta* se o
   workspace 22 não tiver exemplares de todos os tipos preenchidos.
3. **Upload de anexo**: enviar 1 PDF pequeno ao sandbox para medir limite de tamanho e
   shape da resposta.
4. **`board_relation` cross-workspace**: confirmar se a conexão exige boards no mesmo
   workspace. ⚠️ Antes disso: `/boards/{id}/links` e `/mirror-values` respondem 403 para
   o token de API atual (F0.13) — resolver escopo/permissão do token primeiro.
5. **`time_tracking` via API**: confirmar se `POST /columns` aceita o tipo.
6. **Escopos de token**: obter o catálogo de escopos dos tokens de API (UI de Settings ou
   time do Sunday) e emitir o token de serviço com os escopos necessários (incluindo
   `search`, ausente no token atual).
7. **Shape de comments/attachments**: assim que existir item com comentário/anexo num
   board acessível (ou no sandbox), capturar o shape real de leitura.

### F0.11a Autorização de tokens de API (investigação do 403, 2026-08-10)

> Investigado **somente por leitura** (bundle público do SPA + sondagens GET sem auth).
> O backend não é inspecionável (repositório não acessível a este ambiente), então a regra
> exata do guard de token é inferível apenas até o limite documentado abaixo.

**Modelo de acesso do Sunday (catálogo literal da tela Admin → Acessos):**

| `access_level` | Workspaces | Boards | Gestão |
|---|---|---|---|
| `owner` | todos, mesmo sem ser membro | todos, mesmo sem ser membro | tudo (inclusive Owners; teto de 3) |
| `super_admin` | todos | todos | tudo, exceto Owners |
| `admin` | vê/abre todos (pode gerenciar sem se adicionar) | **só boards dos quais é dono/membro ou de workspaces dos quais faz parte** — a menos que o escopo `boards` libere gestão | conforme `admin_scopes` |
| `contributor` | só onde é membro | só boards próprios, com membership, **ou ligados a um workspace do qual faz parte** | cria/edita o próprio trabalho |
| `reader` | só onde é membro (leitura) | somente leitura | nada |

- `admin_scopes` são **escopos administrativos de gestão**, só têm efeito quando
  `access_level = admin`. Valores conhecidos no frontend: `people`, `boards`,
  `module:growth`, `team:b2c` (famílias `module:*` e `team:*`). Não são scopes de API.
- Quem altera nível/escopos: tela Admin (People) via `PATCH /users/{id}/access` com
  `{access_level, admin_scopes}` — acessível a `owner`/`super_admin`/`admin` com escopo
  `people` (há também um atalho por `hierarchy_level >= 13` num helper de UI). Um
  `contributor` **não** consegue atribuir escopos a si mesmo.
- `membership = member` é o papel **dentro do workspace** (`POST /workspaces/{id}/members`
  aceita `{user_id, role}` com default `"member"`; há `PATCH .../members/{id}/role`).

**Tokens de API (Settings → API Access):**

- Endpoints: `GET /auth/me/api-tokens` (lista), `POST /auth/me/api-tokens` (cria),
  `DELETE /auth/me/api-tokens/{id}` (revoga). *Nota: com autenticação por token, a rota de
  listagem responde 403 — gestão de tokens é exclusiva de sessão (F0.13).*
- Payload de criação: **somente `{name}`** (opcional). A resposta traz `{secret, token}`
  e o secret aparece uma única vez. **Não existem** campos de scopes, permissions, role,
  board_ids ou workspace_ids na criação — nem na UI nem no service do SPA. O usuário não
  tem nenhum controle sobre as permissões do próprio token.
- Texto oficial da página: "Conecte o Claude, o Cursor ou qualquer IDE diretamente à sua
  conta do Sunday. Gere um token pessoal e entregue ao assistente — ele passa a criar
  tarefas, comentar e **agir como você**, via API."
- **Porém, o backend aplica restrições próprias aos tokens** (comprovado na leitura
  autenticada, F0.13), em duas camadas distintas:
  1. **Escopos de token server-side**: `GET /boards/search` → 403 `"Este token não tem o
     escopo \"search\" necessário para esta ação."`. Ou seja, tokens têm um conjunto de
     escopos atribuído pelo backend na emissão; o catálogo não é observável por leitura e
     não há UI para alterá-lo.
  2. **Rotas exclusivas de sessão (JWT)**: `GET /boards/{id}/views`, `/links`,
     `/mirror-values`, `GET /boards/me/items` e `GET /auth/me/api-tokens` → 403 `"Este
     token de acesso não pode usar esta rota. Excluir ou alterar configurações exige
     login."` — nenhum token de API passa nessas rotas, independente de escopo.
- Conclusão: o token herda a **identidade** do usuário (age como ele nos boards que ele
  acessa), mas com um **subconjunto** de rotas/escopos definido pelo backend.

**Causas confirmadas de 403 com token (nenhuma é falta de acesso do usuário):**

1. **ID errado**: `GET /workspaces/22` retorna em `boards[]` o `id` do **vínculo**
   workspace-board e o `board_id` real. Usar o id do vínculo em `/boards/{id}` produz 403
   (anti-enumeração). Com o `board_id` correto, board, grupos, colunas, itens, values e
   automações respondem **200** para o token `contributor` (F0.13).
2. **Escopo de token faltante**: só observado em `/boards/search` (escopo `search`).
3. **Rota exclusiva de sessão**: views, links, mirror-values, me/items e gestão de
   tokens — bloqueadas para qualquer token de API.

Impacto prático: a leitura de conexões entre boards (`/boards/{id}/links` e
`/mirror-values`) está bloqueada para tokens — destravar com o time do Sunday antes da
Fase 1 (é pré-requisito para migrar `board_relation`).

### F0.12 Segurança

- Nenhum secret foi impresso, copiado ou registrado em log. No Sunday, o board
  `Legal - Acessos` está vazio; foram consultados apenas seu esquema e a lista vazia de
  itens, sem leitura de values.
- As consultas ao Monday foram exclusivamente de leitura (boards, grupos, colunas,
  contagens e datas de criação de itens; nenhum conteúdo de item foi exportado).

### F0.13 Resultado autenticado na API real (2026-08-10)

Todas as chamadas desta subseção foram `GET` ou `OPTIONS`. Não houve criação, alteração,
upload, arquivamento ou exclusão no Sunday nem no Monday.

**Autenticação e acesso**

- Os dois secrets esperados estavam disponíveis na VM. O conteúdo do token não foi
  exibido.
- `GET /auth/me`, `GET /workspaces/mine`, `GET /workspaces/22` e `GET /boards`
  responderam 200.
- Workspace `22`: **Support - Finance, Legal, People**, slug `support`, ativo; o token é
  `member`. A resposta informou 6 boards e 5 membros.
- `GET /auth/me` identifica o **usuário dono do token** (token pessoal, emitido pelo
  usuário Ivo, `access_level: contributor`, `admin_scopes: []`) — não há identidade de
  serviço separada.
- **Tokens de API têm escopos**: `GET /boards/search` respondeu 403 com
  `"Este token não tem o escopo \"search\" necessário para esta ação."` — permissão por
  funcionalidade. O catálogo de escopos não é observável por leitura (`GET
  /auth/me/api-tokens` também é bloqueado para tokens); levantar na emissão do token de
  serviço.
- O token lê board, colunas, grupos, itens, values e automações. `GET /boards/{id}/views`,
  `GET /boards/{id}/links`, `GET /boards/{id}/mirror-values`, `GET /boards/me/items` e
  `GET /auth/me/api-tokens` responderam 403 (`"Este token de acesso não pode usar esta
  rota. Excluir ou alterar configurações exige login."`): essas rotas exigem login e não
  aceitam este token de API — **impacto direto** na leitura de conexões/espelho
  (`board_relation`), que precisa ser destravada por escopo/permissão antes da Fase 1.
  `GET /boards/{id}/members` e `/capabilities` responderam 404; membros e
  capabilities vêm embutidos em outras respostas.

**Boards, grupos e colunas reais**

| Board (ID real) | Grupos (`id`: nome) | Colunas (`id`: nome — tipo) |
|---|---|---|
| Weekly Support (`70`) | `216`: Itens | `386`: Nome — `text`; `387`: Status — `status`; `388`: Responsável — `people`; `389`: Data — `date`; `390`: Área — `dropdown` |
| Legal - Audiências (`72`) | `218`: Itens; `219`: Audiencias Pendentes | `396`: Nome — `text`; `397`: Status — `status`; `398`: Responsável — `people`; `399`: Data — `date`; `400`: Área — `dropdown` |
| Cronograma + Processos Finance (`74`) | `224`: teste; `221`: teste; `232`: Tarefas - Fechamento mensal - Interno; `231`: Tarefas Diárias; `233`: Fechamento mensal - Envios Contamac; `234`: Fechamento Brain - Dashboard Finance; `235`: Check list Contábil; `236`: Automatizações - Eficiência, eficiência e eficiência; `237`: Auditoria | `409`: Nome — `text`; `424`: COMO FAZER/DESCRIÇÃO — `text`; `413`: Área — `dropdown`; `411`: Responsável — `people`; `427`: Mês — `text`; `412`: PRAZO — `date`; `410`: Status — `status`; `426`: Drive/Evidência — `text` |
| Legal - Controle de Assinaturas - Jan & Luciano (`77`) | `227`: Itens | `428`: Nome — `text`; `429`: Status — `status`; `430`: Responsável — `people`; `431`: Data — `date`; `432`: Área — `dropdown` |
| Legal - Acessos (`78`) | `228`: Itens | `433`: Nome — `text`; `434`: Status — `status`; `435`: Responsável — `people`; `436`: Data — `date`; `437`: Área — `dropdown` |
| Legal - Seguros (`79`) | `229`: Itens | `438`: Nome — `text`; `439`: Status — `status`; `440`: Responsável — `people`; `441`: Data — `date`; `442`: Área — `dropdown` |

O `id` do vínculo retornado por `GET /workspaces/22` é, respectivamente, `57`, `59`,
`63`, `66`, `67` e `68`; não deve ser usado como board ID. Os IDs reais são os da tabela.

**Conteúdo e shapes observados**

| Board | Itens | Values | Comentários | Anexos | Automações |
|---|---:|---:|---:|---:|---:|
| Weekly Support (`70`) | 12 | 0 | 0 | 0 | 0 |
| Legal - Audiências (`72`) | 9 | 0 | 0 | 0 | 0 |
| Cronograma + Processos Finance (`74`) | 166 | 273 | 0 | 0 | 0 |
| Legal - Controle de Assinaturas - Jan & Luciano (`77`) | 0 | 0 | 0 | 0 | 0 |
| Legal - Acessos (`78`) | 0 | 0 | 0 | 0 | 0 |
| Legal - Seguros (`79`) | 0 | 0 | 0 | 0 | 0 |

- Itens são retornados diretamente como array. O shape real inclui `id`, `board_id`,
  `group_id`, `parent_item_id`, `name`, `description`, `status`, `target_date`,
  responsáveis, campos de auditoria e `custom_fields`. Dois dos 12 itens de Weekly
  Support têm `parent_item_id`.
- Os campos das 5 colunas de sistema (`status`, `owner_user_id`, `target_date`, `area`)
  moram **no próprio item**, não em `values`; e cada coluna tem, além do `id` numérico,
  um **`key` semântico estável** (sistema: `name`, `status`, `owner`, `target_date`,
  `area`; custom: slug do label, ex. `mes`, `drive_evidencia`) — útil para o de-para.
- **Correção (data com hora)**: `target_date` retorna ISO datetime completo
  (`"2026-07-28T12:00:00.000Z"`) e a coluna `date` tem o setting `include_time` — a
  limitação "sem data-com-hora" registrada em F0.4/F0.8 estava **errada**; o formato de
  escrita com hora segue pendente de teste.
- `area` (dropdown de sistema) retorna string livre (ex.: `"Consumidor"`) mesmo com
  `settings.options: []` — o vocabulário do dropdown de sistema vem de `area_options`
  do board/workspace, não das options da coluna.
- Values são buscados por item em `GET /boards/items/{id}/values` e têm as chaves
  `id`, `item_id`, `column_id`, `value`, `updated_at`, `updated_by_user`. Os 273 values
  reais encontrados são strings nas colunas `text` `424`, `426` e `427`; os demais
  formatos da tabela F0.4 ainda não foram comprovados contra valores persistidos.
- Todas as consultas de comentários e anexos responderam 200 com arrays vazios. Isso
  confirma as rotas de leitura, mas não o shape de um registro preenchido.
- `GET /boards/{id}/automations` respondeu 200 para os seis boards, todos com array vazio.
  Portanto, o shape persistido de automação e a ação `webhook` não foram confirmados por
  leitura real.
- Os seis boards usam `hierarchy_depth=1`, status de sistema `to_do`/`follow_up`/`done` e
  capabilities `process=false`, `subitems=false`, `approvals=false`,
  `time_tracking=false`, `calendar_anchor=true`.

**Paginação e rate limit**

- `GET /boards?limit=1` retornou os 6 boards.
- `GET /boards/72/items?limit=1` retornou os 9 itens e
  `GET /boards/74/items?limit=1&page=1` retornou os 166 itens.
- Não houve campos nem headers de paginação. Para essas coleções, `limit` e `page` foram
  ignorados e a resposta foi a lista completa.
- Nenhuma resposta trouxe `RateLimit-*`, `X-RateLimit-*` ou `Retry-After`. Não se conclui
  que a API seja ilimitada; apenas que ela não publica esses dados nas respostas testadas
  (~370 requests em rajada sem nenhum 429).
- As respostas trazem **`ETag`** fraco e a API honra `If-None-Match` → **304 Not
  Modified** — bom para reduzir o custo do polling (mitiga o N+1 de values).
- `OPTIONS` responde 204. Infra: Cloud Run atrás do Google Frontend (HTTP/2),
  `x-powered-by: Express`, `x-cloud-trace-context` presente.

**Correções sobre as hipóteses anteriores**

1. O workspace 22 já tem seis boards, mas só **Legal - Audiências** e **Legal - Controle
   de Assinaturas - Jan & Luciano** correspondem diretamente ao escopo integrado. Não
   existem ainda os boards `procons`, `prazos`, `processos judiciais`, `processos
   trabalhista`, `kpi - processos consumidores` e `Contratos`.
2. O Controle (`77`) ainda é um template vazio, com um grupo e cinco colunas genéricas;
   não possui as filas Jan/Luciano nem o esquema necessário à migração.
3. A listagem de boards dentro do workspace usa dois IDs distintos (`id` do vínculo e
   `board_id` real), detalhe ausente no levantamento pelo bundle.
4. As rotas de coleção `/workspaces/22/boards` e `/workspaces/22/members` não existem;
   boards e membros vêm embutidos em `GET /workspaces/22`.
5. O catálogo de 23 tipos continua confirmado no SPA, mas a API real do workspace só
   comprovou cinco tipos de coluna e values persistidos apenas para `text`.
6. A coluna `date` suporta hora (`include_time` + `target_date` em ISO datetime) — a
   hipótese "sem data-com-hora" (F0.4/F0.8) foi **corrigida**.
7. Existe um board **Legal - Acessos** (`78`, vazio) no workspace 22, apesar da decisão 6
   (Acessos fora do escopo; credenciais → Secret Manager) — alinhar com o time antes da
   Fase 1 para não sinalizar que credenciais entrarão no Sunday.
8. O board **Legal - Audiências** (`72`) já tem 9 itens reais de uso manual — a Fase 2
   precisa **reconciliar** com o conteúdo existente, não só importar do Monday.

### F0.14 Testes controlados de escrita e decisão Go/No-Go

> Autorização de 2026-08-11: escrita permitida **somente** no board sandbox `80`
> ("SANDBOX - API SUNDAY - NÃO USAR", ws 22) e no board "SANDBOX - API SUNDAY - RELATION"
> (criado/reutilizado via API, id `81`). Decisões de projeto: trabalhar com a API
> existente (sem depender do time do Sunday); migração não precisa ser 100% automática,
> mas a complementação manual deve ser minimizada seguindo a ordem nativo →
> transformação → fallback em código → tabela local → outro tipo de coluna →
> comentário/anexo → manual.

**Status de execução (2026-08-11): concluído.** `SUNDAY_API_TOKEN` e `SUNDAY_API_URL`
estavam disponíveis (valores não exibidos). Antes da primeira escrita, `GET /boards/80`
retornou exatamente **"SANDBOX - API SUNDAY - NÃO USAR"** e `GET /workspaces/22`
confirmou `board_id: "80"`. O segundo sandbox já existia no workspace como board **`81`**;
nenhum board novo foi criado. A execução produziu 65 registros: 33 passos HTTP 2xx,
30 passos não-2xx e 2 registros de observação do webhook. Considerando os oito testes
funcionais como unidades, **1 passou integralmente (webhook) e 7 falharam ou ficaram
parciais**. Relatório sanitizado:
`docs/sunday-fase0-write-report-2026-08-11.json`.

Antes da execução, os guard-rails foram reforçados para validar o vínculo do board 80
ao workspace 22, aceitar somente o payload exato do sandbox de relação, bloquear
mutação direta destrutiva de board e remover token, headers sensíveis, identificadores
de usuário e dados de identidade do relatório. Todos os nomes, textos, URLs e o PDF
enviados pelos testes eram fictícios.

**Resultados reais dos Testes 1–8**

| Funcionalidade | Endpoint | Método | Payload confirmado | HTTP | Resultado | Limitação | Fallback |
|---|---|---|---|---|---|---|---|
| T1 — grupo | `/boards/80/groups`; `/boards/groups/{id}` | `POST`; `PATCH` | `{"name":"TESTE-FICTICIO Grupo A","color":"blue"}`; alteração de `name` | `201`; `403` | criação confirmada; alteração negada | token não pode alterar/excluir configuração; exclusão não foi exercitada | criar grupos via API; renomear/excluir manualmente na configuração |
| T1 — item/status | `/boards/80/items`; `/boards/items/{id}`; `/status` | `POST`; `GET`; `PATCH` | `name`, `group_id`; depois `name`, `description`; `status`, `cascade` | `201`; `200`; `200` | criar, listar e alterar item e status de sistema funciona | exclusão de item não foi exercitada | nativo para o fluxo; limpeza manual residual |
| T1 — coluna/value | `/boards/80/columns`; `/boards/items/{id}/values/{column_id}` | `POST`; `PATCH`; `GET` | coluna `text`; value textual fictício | `403`; `404`; `200` | coluna não criada; sem `column_id`, a escrita de value não ocorreu; leitura retornou lista vazia | criação/alteração de coluna exige login; escrita de values essenciais continua **não confirmada** | pré-configurar colunas manualmente e repetir values; sem essa confirmação, não iniciar o adapter |
| T2 — tipos de coluna | `/boards/80/columns` | `POST` | `label`, `type` e opções quando aplicável | `403` em 20/20 tipos | nenhum tipo foi criado pela API | `text`, `long_text`, `number`, `status`, `status_multi`, `dropdown`, `date`, `checkbox`, `people`, `timeline`, `rating`, `tags`, `link`, `file_link`, `email`, `phone`, `dependency`, `formula`, `time_tracking` e `creation_log` não foram validados para escrita | configuração manual única; transformar tipos não suportados, mas values ainda precisam de reteste |
| T3 — `board_relation` | `/boards/81/items`; `/boards/80/columns`; `/boards/items/{id}/values/{column_id}` | `POST`; `POST`; `PATCH`/`GET` planejados | item alvo fictício; coluna com `source_board_id:"81"`; relação `{links:[{item_id}]}` planejada | `201`; `403`; não executados | item alvo criado; relação não pôde ser criada, preservada, relida nem reconstruída | bloqueio ocorreu na criação da coluna, antes do teste de values | tabela local de relações + IDs externos; `/links` é dispensável para o fallback, mas o fluxo nativo segue **não determinado** |
| T4 — mirror | `/boards/80/columns`; `/boards/items/{id}/values`; `/boards/80/mirror-values` | `POST`; `GET`; `GET` | coluna `mirror` com board/coluna de origem | `403`; `200`; `403` | mirror não criado; values ficaram vazios; rota especializada negada | API token não configura mirror nem acessa `mirror-values` | lookup/cópia materializada no sync usando cache de items+values |
| T5 — comentários | `/boards/items/{id}/comments`; `/boards/comments/{id}` | `POST`; `GET`; `PATCH`; `DELETE` | `body` fictício e `kind:"reply"` | `201`; `200`; `403`; `200` | criar, listar e excluir funciona; editar não | autoria será a conta técnica; edição exige login | comentários imutáveis: excluir+recriar antes do cutover; depois, acrescentar correção |
| T6 — anexos | `/boards/items/{id}/attachments/file`; `/link`; `/attachments` | `POST` multipart; `POST` JSON; `GET` | PDF fictício de 193 bytes; URL/filename fictícios | `403`; `201`; `200` | upload binário falhou; anexo por link e listagem funcionam | upload de arquivo exige login | armazenar em Drive/GCS e anexar link estável; upload manual só para exceções |
| T7 — `time_tracking` | `/boards/80/columns` | `POST` | `{"label":"TESTE-FICTICIO time_tracking","type":"time_tracking"}` | `403` | tipo e values não validados | criação de coluna exige login | coluna `number` criada manualmente para total histórico; cronômetro futuro manual, se necessário |
| T8 — `item_created` → webhook | `/boards/80/automations`; `/boards/80/items`; `/automations/{id}/runs` | `POST`; `POST`; `GET`; `PATCH` | trigger `item_created`, action `webhook`, URL de eco; item fictício | `201`; `201`; `200`; `200` | automação criada, callback recebido e automação desativada | timeout não observável; runs ficaram `success` mesmo quando o receptor respondeu 500 | webhook é utilizável, mas polling+ETag continua sendo a fonte resiliente |

**Webhook observado.** O callback de sucesso foi `POST`, `Content-Type:
application/json`, `User-Agent: node`, com body
`{"board_id":"80","item_id":"7638","item_name":"TESTE-FICTICIO dispara webhook OK"}`.
Também foram observados `Accept: */*`, `Accept-Encoding: br, gzip, deflate` e
`Content-Length: 82`; nenhum header sensível foi preservado. Com o receptor em HTTP
500, foram observadas **6 requisições adicionais** em aproximadamente 42 segundos,
mas o relatório dessa fase preservou apenas timestamps e houve criação concorrente de
itens no mesmo sandbox. Portanto, não é possível separar retries de novos eventos. O
Sunday registrou os runs como `success` apesar do 500. Método, headers e body
específicos da fase 500, retries, política após a janela observada e timeout:
**NÃO DETERMINADOS**.

**Teste extra de subitem.** `PATCH /boards/80` com `{"hierarchy_depth":2}` retornou
`403`, mas `POST /boards/80/items` com `parent_item_id` retornou `201`; o board já
aceitava hierarquia. Assim, criar subitem é nativo quando a hierarquia foi
pré-configurada; alterar essa configuração exige login.

Os Testes 9–13 são analíticos e foram **concluídos** com os dados reais já coletados
(F0.7 e F0.13), com os ajustes de escrita abaixo:

**T9 — Polling (arquitetura principal de Contratos).** Volume real do Controle no
Monday: 1.607 itens (506 criados em 12 meses); recorte migrado estimado em 500–700
itens. No Sunday, `GET /boards/{id}/items` traz a coleção completa numa chamada (sem
paginação) e values são por item (N+1). Ciclo proposto para o
`contratos-sync-controle`: (1) `GET items` com `If-None-Match` (ETag confirmado —
304 quando nada mudou: ciclo de **1 request**); (2) se 200, diff por `id` (novos) e
`updated_at`/hash (alterados) contra o cache local persistido
(`data/sunday-cache-<board>.json`); (3) `GET values` **só** dos itens novos/alterados;
(4) processar e gravar checkpoint. Primeiro ciclo (cache frio): ~1 + N requests
(~600 para o Controle; a leitura autenticada fez ~370 requests em rajada sem 429),
estimado em 2–4 minutos sequencial. Ciclos estáveis: 1–10 requests, segundos. Risco de
rate limit: não publicado pela API; mitigar com burst moderado e backoff exponencial em
429/5xx. **Viável.**

**T10 — Search dispensável.** Identificadores usados pelo código atual: protocolo
Procon, CPF, CNPJ, número CNJ, Autentique ID (no texto do link do item), título
normalizado de contrato. Todos passam a ser resolvidos por **índice local** construído
sobre o cache de items+values do T9 (dicionários por coluna-chave, reconstruíveis a
qualquer momento — o cache não é fonte de verdade). `/boards/search` (escopo `search`
ausente no token) fica **dispensável**; a busca textual nunca foi usada pelo código.

**T11 — Matriz de compatibilidade Monday → Sunday (uso real da B4A), atualizada pós-escrita:**

| Recurso Monday | Uso real | Equivalente Sunday | Estratégia | Auto/Manual | Risco |
|---|---|---|---|---|---|
| Boards (8 integrados + ~15 de dados) | estrutura dos domínios | `POST /boards` + grupos/colunas | pré-criar estrutura e IDs; criação de board não foi exercitada nesta execução | Manual + Auto | médio |
| Grupos (meses/filas/estágios) | filas Jan/Luciano, grupos por ano | `POST /boards/{id}/groups` | criação automática (`201`); renomear/excluir manualmente (`403`) | Auto + Manual residual | baixo |
| Items | casos, contratos, prazos | `POST /boards/{id}/items` | migração com mapa de IDs | Auto | baixo |
| Status (44 colunas) | Status/Quem Assina/Tipo/causas | coluna `status`/`dropdown` + Status de sistema | colunas/opções pré-configuradas manualmente; values precisam de reteste | Manual + pendente | **alto** |
| Datas (20) | prazos, audiências | `date` (`include_time` p/ hora) | coluna pré-configurada; value e data-com-hora não confirmados | Manual + pendente | **alto** |
| Pessoas (6) | responsáveis | `people` | coluna pré-configurada; value não testado para evitar usar identidade real | Manual + pendente | **alto** |
| Textos/números/e-mails/links | CNPJ, CIP/FA, valores, provisões | `text`/`long_text`/`number`/`email`/`link` | colunas pré-configuradas; escrita de values precisa de reteste | Manual + pendente | **alto** |
| Arquivos (8 colunas file) | notificações Procon, contratos | anexo por link | Monday/Drive/GCS → URL estável → `attachments/link` (`201`) | Auto c/ transform. | médio |
| Updates/timeline | histórico dos casos | `comments` | criar comentários em ordem; não editar | Auto c/ transform. | baixo |
| Conexão de quadros (5) | Prazos/Audiências→Processos; Controle→Contratos | não confirmado | tabela local de relações + IDs externos | Auto (fallback) | médio |
| Mirror | espelhos nos quadros de legal | leitura bloqueada p/ token | cópia do valor no sync (lookup no nosso código) | Auto (fallback) | baixo |
| Automações (2 regras) | Assinado→Contratos; mestre→audiências | webhook confirmado; sem `create_item` cross-board | polling principal + regra no código; webhook como aceleração | Auto (código) | médio |
| Busca por valor de coluna | dedup protocolo/CPF/CNJ | inexistente | índice local (T10) | Auto (fallback) | baixo |
| IDs externos | Autentique ID, estado local | — | coluna `text` "Monday ID"/"Autentique ID" + tabela de mapeamento | Auto | baixo |
| Subitems | aditivos em Contratos (`register_contrato_subitem`), subelementos | `parent_item_id` com board pré-configurado | migrar como filhos nativos (`201`) | Auto | baixo |
| Histórico (12 meses + abertos) | ~1.279 itens recentes de ~4.391 | — | recorte na exportação | Auto | baixo |
| `location` (3) | local de audiência/origem | inexistente | degradar para `text` | Auto c/ transform. | nenhum |
| `formula` (2) | saving/saved | `formula` com expressão própria | recriar expressão à mão (2 colunas) | **Manual** | nenhum |
| `time_tracking` (2) | controle de tempo | criação por token negada; values desconhecidos | preservar total em `number` "Horas (Monday)" pré-criada manualmente | Auto c/ fallback + **manual** | médio |
| Views/filtros | visões de trabalho | `POST /boards/{id}/views` | recriar principais; refinamento manual | Semi | nenhum |

**T12 — Complementação manual (mínima, com fallback avaliado antes):**

1. **Fórmulas** (2 colunas: "saving" em Processos Judiciais, "Saved" em Trabalhista).
   Motivo: linguagem de expressão própria do Sunday; transpilar 2 fórmulas não compensa.
   Recomendação: **complementar manualmente**.
2. **Estrutura de colunas e alterações de grupos.** A API permitiu criar grupo, mas
   negou criar qualquer uma das 20 colunas testadas e negou renomear grupo. Portanto,
   a estrutura precisa ser pré-configurada pela interface. Isso deixa de ser um ajuste
   manual pequeno: é pré-condição para retestar values e sair do No-Go.
3. **Cronometragem futura de `time_tracking`** (2 colunas). Preservar o histórico em
   coluna `number` pré-criada manualmente; configurar cronômetro futuro só se o time
   realmente usar o recurso.
4. **Views/filtros e revisão de membros por board** (~8 boards). Recomendação:
   **complementar manualmente** por ser preferência visual e conferência humana.
5. **Automações** (2 regras): portadas para o nosso código (não é manual recorrente;
   é implementação já prevista). Recomendação: **automatizar**.

O proxy anterior por contagem de colunas (A 82% / B 15% / C 3%) não pode mais ser
usado como evidência de escrita: nenhum dos 20 tipos foi criado e nenhum value foi
gravado. A estrutura manual pode ser aceitável como tarefa única, mas a escrita de
values não confirmada permanece classe **D** até o reteste em colunas pré-configuradas.

**T13 — Rastreabilidade e mapa de IDs.** Tabela persistente
`data/monday-sunday-map.json` com uma linha por item:
`{monday_board_id, monday_item_id, sunday_board_id, sunday_item_id, domain,
migration_status, migrated_at, error}` + seções de de-para de boards, grupos e colunas
(`monday_column_id → sunday_column_id`, necessário para migrar values e para o período
de sombra do adapter). Redundância à prova de perda do arquivo: cada board migrado
ganha coluna `text` **"Monday ID"** preenchida com `board_id/item_id` de origem —
permite reconstruir o mapa inteiro por leitura do Sunday. Não implementado ainda.

**Matriz Go/No-Go final pós-escrita (A nativo · B fallback/transformação · C manual
aceitável · D bloqueante):**

| Requisito | Classe | Observação |
|---|---|---|
| Criar/listar/alterar itens e status de sistema | A | `POST`/`GET`/`PATCH` confirmados |
| Criar grupos | A | `POST` confirmado |
| Renomear/excluir grupos e configurar boards/colunas | C | exige login/interface; configuração única |
| Escrever/alterar values essenciais | **D** | não testado: criação da coluna falhou e deixou `column_id` vazio |
| Status, datas, textos, números, links, e-mails | **D** | nenhum value confirmado; pré-configurar e retestar |
| Pessoas | **D** | não testado, inclusive para não usar identidade real |
| Subitens (aditivos Contratos) | A/C | criação nativa; `hierarchy_depth` exige configuração manual |
| Arquivos (PDF Procon/Contratos) | B | Drive/GCS + anexo por link; upload binário retornou 403 |
| Updates/histórico | A/B | criar/listar/excluir comentário funciona; editar vira correção adicional |
| Conexões entre quadros | B | nativo não determinado; tabela local de relações dispensa `/links` |
| Mirror | B | cópia/lookup no sync |
| Automações cross-board | B | nosso código |
| Evento de item criado (Controle) | A/B | webhook nativo confirmado; polling+ETag como resiliência |
| Busca por valor | B | índice local |
| Rastreabilidade de IDs | B/D | mapa local funciona; coluna Monday ID depende do reteste de values |
| `location` | B | → text |
| `formula` | C | 2 colunas |
| `time_tracking` | B/C | total em `number` + configuração manual |

**Decisão: NO-GO para iniciar `sunday/client.py`.** O bloqueio não é a ausência de
`/links`, `/mirror-values`, search, mirror ou webhook: todos têm fallback razoável, e
o webhook foi confirmado. O bloqueio é mais básico: a execução não confirmou escrita
de **nenhum value de coluna**, operação essencial para contratos, jurídico e Procon.
Implementar o adapter agora cristalizaria um contrato de API ainda não demonstrado.

**Critério objetivo para reavaliar o Go:** pré-configurar manualmente no board 80
colunas fictícias `text`, `number`, `status`, `date`, `link`, `email` e
`board_relation` apontando para o board 81; então repetir `PATCH` e `GET
/boards/items/{id}/values/{column_id}` para criar, alterar, reler e reconstruir os
values. `long_text`, `dropdown`, arquivos e `time_tracking` podem usar os fallbacks
documentados se seus testes continuarem falhando. Até esse reteste, não implementar
`sunday/client.py`.
