# Migração Monday → Sunday (temas de Legal) — plano estrutural

> **Status: Fase 0 (descoberta) concluída, incluindo a validação autenticada de leitura
> (2026-08-10) e os testes controlados de escrita no sandbox (2026-08-11) — decisão
> **GO** para iniciar `sunday/client.py` (ainda não implementado).** Este documento
> estrutura a migração do workspace de Legal do Monday (`beauty4all.monday.com`,
> workspace `2334257`) para o Sunday (`https://sunday.b4a.ai/workspaces/22`). **Nenhum
> comportamento de produção foi alterado**: nenhum código de integração foi modificado,
> nenhum dado real foi migrado, nenhum quadro de produção foi criado ou alterado (Monday
> e todos os boards reais do Sunday permanecem intactos); a escrita de testes ocorreu
> exclusivamente nos boards sandbox `80`/`81` (`SANDBOX - API SUNDAY - NÃO USAR` /
> `... - RELATION`, ws 22) com dados 100% fictícios. O resultado da Fase 0 está na seção
> ["Resultado da Fase 0 - Sunday API"](#resultado-da-fase-0---sunday-api); a validação
> autenticada de leitura está em F0.13, os testes de escrita e a decisão final em F0.14.

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
| `add_file_to_column` (PDF) | `POST /boards/items/{id}/attachments/file` — **bloqueado para o token de API** (403, F0.14); usar `attachments/link` após subir o arquivo no Drive/GCS | média (funciona só com o fallback via link) |
| Colunas de link | `attachments/link` ou coluna própria de link | alta (confirmado por escrita, `201` — F0.14) |
| `board_relation` (conexão de quadros) | `POST /boards/items/{id}/values/{colId}` (não `/links`, que é `403` para o token também na escrita — F0.14) | baixa (criação da coluna via `POST /boards/{id}/columns` bloqueada p/ token — 403; esquema precisa ser criado manualmente 1x por board antes de o value poder ser confirmado) |
| Automação Monday (Tipo→Contratos; mestre→audiências) | `POST /boards/{id}/automations` | média (catálogo de gatilhos/ações a confirmar) |
| Webhook de item criado (Controle) | **sem equivalente visível** → polling, automação ou feature nova | baixa — decisão em aberto |
| Status/labels (`status` column settings) | coluna de status Sunday + `PATCH /boards/items/{id}/status` | alta |
| URL do item (`https://<slug>.monday.com/boards/{b}/pulses/{i}`) | `https://sunday.b4a.ai/workspaces/22/boards/{b}?item={i}` (formato a confirmar) | média |

## 5. Decisões (fechadas em 2026-08-10; detalhes técnicos na seção da Fase 0)

1. **Eventos de saída**: **polling** como arquitetura inicial, partindo do cron
   `contratos-sync-controle`. A Fase 0 confirmou (F0.14, teste de escrita real) que a
   automação `webhook` funciona nativamente: `POST` com `Content-Type: application/json`,
   entrega em ~1s após o `item_created`, corpo `{"board_id","item_id","item_name"}`, sem
   header de assinatura/HMAC observável; nenhum retry foi demonstrado em ~3min de janela
   de erro 5xx no destino (as requisições extras observadas eram eventos concorrentes,
   não reentregas — ver F0.14). `webhook` fica como upgrade de latência do polling (V2),
   tratado como fire-and-forget, não como substituto. Nada muda em produção por ora.
2. **Token de serviço**: Fase 0 usa os secrets `SUNDAY_API_TOKEN` + `SUNDAY_API_URL` já
   cadastrados. Antes do cutover, será emitido token por conta de serviço dedicada B4A.
   O token atual é **pessoal** (usuário do token, `access_level: contributor`) e não
   gerencia esquema — qualquer criação/alteração de coluna, renomeação de grupo,
   configuração de board ou upload de arquivo binário retorna `403` ("requer login"),
   independentemente de escopo (F0.11a/F0.14); isso não é resolvido emitindo um token
   diferente, é uma restrição de **tipo de credencial** (token de API vs. sessão de
   login). O esquema de colunas customizadas é criado manualmente uma vez por board na
   Fase 1; o token de serviço cobre normalmente todo o resto (itens, values de colunas
   já existentes, comentários, anexos por link, automações).
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
| Webhook de item criado (challenge) | Sem registro de webhook externo; ação `webhook` de automação confirmada por escrita (F0.14, ~1s de latência, fire-and-forget) como upgrade do polling |
| Automação cross-board (Assinado→Contratos; mestre→audiências) | Inexistente; vai para nosso código |
| `items_page_by_column_values` | Inexistente; filtro client-side (`/boards/search` além de textual exige escopo `search` no token — F0.13) |
| Coluna `file` com upload | Upload binário bloqueado p/ token (403, F0.14); anexos por link (`201`, confirmado) via Drive/GCS |
| Coluna `location` | Degradar para `text` |
| `add_file_to_column` (PDF Procon) | Bloqueado p/ token; `attachments/link` após subir no Drive/GCS (F0.14) |
| Updates na timeline | `comments` (criação/leitura/exclusão confirmadas; edição bloqueada p/ token, não necessária) — equivalente direto |
| Conexão de quadros + espelho | `board_relation` + `mirror` — equivalentes, mas a criação da coluna exige configuração manual 1x/board (token não gerencia esquema, F0.14) |
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

### F0.12 Segurança (Fase 0)

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

**Status de execução (2026-08-11): concluído**, em três rodadas complementares contra o
mesmo sandbox (secrets injetados em VMs paralelas para esta tarefa — ver nota de
execução concorrente): a execução principal (`scripts/sunday_fase0_write_tests.py`,
63 passos, relatório `docs/sunday-fase0-write-report-2026-08-11.json`), um follow-up
que fechou lacunas de DELETE/`/links`/rota de values
(`scripts/sunday_fase0_write_tests_followup.py`, relatório
`docs/sunday-fase0-write-followup-report-2026-08-11.json`) e uma reconfirmação pontual
(item de teste `7650`) que isolou o mecanismo de escrita das colunas de sistema. `GET
/boards/80` confirmou o nome exato **"SANDBOX - API SUNDAY - NÃO USAR"** antes de
qualquer escrita; o segundo sandbox já existia como board `81` (criado por uma das
execuções paralelas) e foi reaproveitado, sem criar um terceiro board. Todos os nomes,
textos, URLs e o PDF usados nos testes eram fictícios; os relatórios foram sanitizados
(sem token, headers sensíveis ou identidade real) antes de serem commitados.

**Nota de execução concorrente:** por esta tarefa ter sido disparada em várias VMs ao
mesmo tempo, o board 80 acumulou grupos/itens fictícios de mais de uma execução, e o
board 81 (RELATION) foi criado por uma delas e reaproveitado pelas demais via dedup. Os
guard-rails baseados em rastreio de recursos próprios (`OWNED`) garantiram que nenhuma
execução escreveu em recursos criados por outra; o único efeito colateral observável foi
ruído na contagem de disparos do webhook (T8), já isolado comparando `automations/{id}/runs`
com o receptor (ver abaixo).

**Resultados reais consolidados (T1–T8 + follow-up + reconfirmação):**

| Funcionalidade | Endpoint | Método | Payload confirmado | HTTP | Resultado | Limitação | Fallback |
|---|---|---|---|---|---|---|---|
| Grupo — criar / renomear | `/boards/80/groups`; `/boards/groups/{id}` | `POST`; `PATCH` | `{"name","color"}`; alteração de `name` | `201`; `403` | criação confirmada; renomear negado | token não altera/exclui configuração | acertar o nome já na criação |
| Item — criar / listar / atualizar / excluir | `/boards/80/items`; `/boards/items/{id}` | `POST`; `GET`; `PATCH`; `DELETE` | `name`, `group_id`, `parent_item_id`; depois `name`, `description`; sem corpo | `201`; `200`; `200`; `200` | CRUD completo confirmado (exclusão: `GET` posterior devolve `404`) | mover item para outro grupo depois de criado exige login (`PATCH .../group` → `403`); `group_id`/`assignee_user_ids` no `PATCH` genérico são **ignorados em silêncio** | criar o item já no grupo certo; reatribuir responsável fica pendente (ver linha de pessoas) |
| Item — status de sistema | `/boards/items/{id}/status` | `PATCH` | `{"status","cascade"}` | 200 | OK | nenhuma | — |
| Item — ler um único item | `/boards/items/{id}` | `GET` | — | 404 | rota não existe | leitura é sempre pela coleção do board | cache local do polling (T9) já cobre |
| **Colunas de sistema do template (`name`/`status`/`owner_user_id`/`target_date`/`area`) — escrever value pela rota errada** | `/boards/items/{id}/values/{column_id}` | `PATCH` | `{"value":...}` | 400 | rejeitado com mensagem **de negócio** (não de permissão): `"System columns são atualizadas via PATCH /boards/items/:id"` | rota errada para este tipo de coluna | usar a rota abaixo |
| **Colunas de sistema — escrever/ler value pela rota certa** | `/boards/items/{id}` | `PATCH` | `{"owner_user_id":"37"}` / `{"target_date":"2026-04-10T09:00:00.000Z"}` / `{"area":"..."}` | 200 (nas 3) | **confirmado e persistido**, reconfirmado de forma independente (item `7650`, releitura via `GET /boards/80/items`); data com hora funciona sem flag extra; `area` (dropdown) aceita texto livre mesmo sem opções cadastradas | nenhuma | — |
| Colunas customizadas — criar (22 tipos distintos testados, 23 tentativas) | `/boards/{id}/columns` | POST | `{"label","type",...}` | 403 em 100% das tentativas | bloqueado — mensagem idêntica de config/login | token não gerencia esquema | criar o esquema **uma única vez por board**, manualmente/via login humano na Fase 1 |
| Colunas customizadas — escrever value (inclusive `board_relation`/`mirror`) | `/boards/items/{id}/values/{column_id}` | PATCH/GET | `{"value":...}` | **não testado** (coluna nunca chegou a existir) | indeterminado empiricamente | bloqueado a montante pela criação da coluna | a mesma rota respondeu `400` de negócio (não `403` de permissão) para colunas de sistema — indício forte de que a rota funcionaria para colunas customizadas; confirmar com 1 coluna text criada pelo app no board 80 + `python scripts/sunday_fase0_write_tests.py --minimal` (PATCH value → GET → PASS/FAIL) |
| `mirror-values` — ler | `/boards/{id}/mirror-values?column_id=` | GET | — | 403 | bloqueado (confirma F0.13) | requer login | cópia/lookup no código de sync |
| `/links` — ler e criar | `/boards/{id}/links` | GET **e** POST | `{"target_board_id":"81"}` | 403 (ambos) | bloqueado para o token também na escrita | requer login | **o fluxo de `board_relation` não pode depender de `/links`** — usar apenas o value da coluna (ver linha acima) e/ou tabela local de relações |
| Criar board | `/boards` | POST | `{"name","description","template_key","workspace_id"}` | 201 | **confirmado** — o board `81` foi criado assim por uma das execuções paralelas | colunas do board novo são só as 5 de sistema | estrutura de colunas customizadas continua manual |
| Habilitar hierarquia do board | `/boards/{id}` | PATCH | `{"hierarchy_depth":2}` | 403 | bloqueado | requer login | não é necessário — subitem funciona sem essa configuração (ver linha abaixo) |
| Criar subitem | `/boards/{id}/items` | POST | `{"name","parent_item_id"}` | 201 | **confirmado**, `parent_item_id` persiste na releitura, mesmo sem `hierarchy_depth` habilitado via PATCH | nenhuma relevante | — |
| Comentário — criar / listar / excluir | `/boards/items/{id}/comments`; `/boards/comments/{id}` | POST; GET; DELETE | `{"body","kind":"reply"}` | 201; 200; 200 | OK | nenhuma | — |
| Comentário — editar | `/boards/comments/{id}` | PATCH | `{"body"}` | 403 | bloqueado | requer login | migração só cria comentário uma vez; edição não é necessária |
| Anexo por link | `/boards/items/{id}/attachments/link` | POST | `{"url","filename"}` | 201 | OK | nenhuma | — |
| Anexo — upload de arquivo binário | `/boards/items/{id}/attachments/file` | POST (multipart) | PDF fictício de 193B | 403 | bloqueado | requer login | subir o arquivo no Drive/GCS (infra já usada em Contratos) e anexar por link |
| Anexo / grupo — excluir; capabilities do board — editar | `/boards/attachments/{id}`; `/boards/groups/{id}`; `/boards/{id}/capabilities` | DELETE; DELETE; PATCH | — | 403 (nos 3) | bloqueado | requer login | limpeza/configuração ficam manuais (config. única) |
| Diretório de usuários | `/users/directory` | GET | — | 200 | OK — retorna dados reais (`id/name/email/phone/avatar_url`) | dado real da B4A na resposta; não commitar em texto puro | montar o de-para e-mail→`user_id` só em memória/cache local |
| Automação `item_created`→`webhook` — criar / desativar | `/boards/{id}/automations`; `/automations/{id}` | POST; PATCH | trigger `item_created`, action `webhook` | 201; 200 | OK | nenhuma | — |
| Entrega do webhook | disparo automático | POST (Sunday → URL configurada) | `{"board_id","item_id","item_name"}` | 200 (recebido) | entrega em **~1s**; `Content-Type: application/json`; `User-Agent: node`; sem header de assinatura/HMAC | sem mecanismo observado de autenticidade por header | segredo compartilhado próprio na URL/query, se expusermos um receptor |
| Retry do webhook em erro 5xx | idem, endpoint alterado para 500 | — | — | 500 (no endpoint) | **esclarecido por cruzamento de dados**: a automação acumulou 18 `runs` e o receptor registrou exatamente 18 requisições, correspondência 1:1 por `item_id`/timestamp — ou seja, as requisições da janela de erro eram **eventos novos concorrentes, não retries**; nenhuma reentrega foi observada nos ~3min da janela | retries além dessa janela e timeout continuam **NÃO DETERMINADOS** | tratar a entrega como fire-and-forget (sem retry garantido) no design; `runs` = `success` mesmo com destino em 500, não usar como confirmação de entrega |
| Runs da automação | `/automations/{id}/runs` | GET | — | 200 | OK — `status:"success"` reflete que a automação disparou, não que o destino respondeu 2xx | idem acima | não usar isoladamente como confirmação de entrega |

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
| Boards (8 integrados + ~15 de dados) | estrutura dos domínios | `POST /boards` + grupos/colunas | criação de board via token **confirmada** (`201`, board 81); colunas customizadas do board novo exigem configuração manual (1x/board) | Auto (board/grupos) + Manual (colunas) | médio |
| Grupos (meses/filas/estágios) | filas Jan/Luciano, grupos por ano | `POST /boards/{id}/groups` | criação automática (`201`); renomear/excluir manualmente (`403`) | Auto + Manual residual | baixo |
| Items | casos, contratos, prazos | `POST /boards/{id}/items` | migração com mapa de IDs | Auto | baixo |
| Status (44 colunas) | Status/Quem Assina/Tipo/causas | coluna `status`/`dropdown` customizada + Status de sistema | coluna customizada pré-configurada manualmente (1x/board); `status`/`dropdown` de **sistema** já confirmados via `PATCH /boards/items/{id}` | Manual (config. 1x) + Auto | médio |
| Datas (20) | prazos, audiências | `date` (`include_time` p/ hora) | coluna customizada pré-configurada (1x/board); campo de sistema `target_date`, inclusive com hora, **confirmado** (item `7650`) | Manual (config. 1x) + Auto | médio |
| Pessoas (6) | responsáveis | `people` | coluna customizada pré-configurada (1x/board); `owner_user_id` de **sistema** confirmado sem expor identidade real (usa só o `user_id` numérico do dono do token) | Manual (config. 1x) + Auto | médio |
| Textos/números/e-mails/links | CNPJ, CIP/FA, valores, provisões | `text`/`long_text`/`number`/`email`/`link` | coluna customizada pré-configurada (1x/board); rota de `values` não exige login para colunas não-sistema (só rejeita por tipo, `400`) — indício forte de que funciona, a confirmar com 1 coluna real na Fase 1 | Manual (config. 1x) + Auto | médio |
| Arquivos (8 colunas file) | notificações Procon, contratos | anexo por link | Monday/Drive/GCS → URL estável → `attachments/link` (`201`) | Auto c/ transform. | médio |
| Updates/timeline | histórico dos casos | `comments` | criar comentários em ordem; não editar | Auto c/ transform. | baixo |
| Conexão de quadros (5) | Prazos/Audiências→Processos; Controle→Contratos | não confirmado | tabela local de relações + IDs externos (`/boards/{id}/links` é 403 para token também no `POST` — o fluxo não pode depender dele) | Auto (fallback) | médio |
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
2. **Estrutura de colunas customizadas e alterações de grupos.** A API permitiu criar
   grupo, mas negou criar qualquer um dos 22 tipos de coluna testados e negou renomear
   grupo. Isso não bloqueia os values das **colunas de sistema** (confirmados via
   `PATCH /boards/items/{id}` — status, pessoas, data com hora, dropdown), mas segue
   como pré-condição para as **colunas customizadas** (inclusive `board_relation` e
   `mirror`): precisam ser pré-configuradas pela interface, uma vez por board, antes de
   o value poder ser escrito/lido por elas. Impacto: ~146 colunas nos 8 boards
   integrados, tarefa única (não recorrente por item). Recomendação: **complementar
   manualmente na Fase 1**.
3. **Cronometragem futura de `time_tracking`** (2 colunas). Preservar o histórico em
   coluna `number` pré-criada manualmente; configurar cronômetro futuro só se o time
   realmente usar o recurso.
4. **Views/filtros e revisão de membros por board** (~8 boards). Recomendação:
   **complementar manualmente** por ser preferência visual e conferência humana.
5. **Automações** (2 regras): portadas para o nosso código (não é manual recorrente;
   é implementação já prevista). Recomendação: **automatizar**.

O proxy anterior por contagem de colunas (A 82% / B 15% / C 3%) não pode mais ser usado
como evidência de escrita para colunas **customizadas**: nenhum dos 22 tipos foi criado
via API. Porém, a escrita/releitura de value nas colunas de **sistema** (status,
pessoas, data com hora, dropdown) está confirmada e é reproduzível — não é correto dizer
que "nenhum value foi gravado". A estrutura de colunas customizadas é uma tarefa manual
aceitável, única por board; não configura classe D (ver Matriz Go/No-Go final).

**T13 — Rastreabilidade e mapa de IDs.** Tabela persistente
`data/monday-sunday-map.json` com uma linha por item:
`{monday_board_id, monday_item_id, sunday_board_id, sunday_item_id, domain,
migration_status, migrated_at, error}` + seções de de-para de boards, grupos e colunas
(`monday_column_id → sunday_column_id`, necessário para migrar values e para o período
de sombra do adapter). Redundância à prova de perda do arquivo: cada board migrado
ganha coluna `text` **"Monday ID"** preenchida com `board_id/item_id` de origem —
permite reconstruir o mapa inteiro por leitura do Sunday. Não implementado ainda.

**Matriz Go/No-Go final (A nativo · B fallback/transformação · C manual aceitável ·
D bloqueante):**

| Requisito | Classe | Observação |
|---|---|---|
| Criar/listar/alterar/excluir itens e status de sistema | A | `POST`/`GET`/`PATCH`/`DELETE` confirmados |
| Criar grupos / criar boards | A | `POST` confirmados (board 81 criado via token); item entra no grupo certo na criação (mover depois exige login) |
| Renomear/excluir grupos e configurar boards/colunas (esquema) | B | exige login/interface; configuração única por board na Fase 1, não recorrente por item |
| Status, datas (com hora), pessoas (`owner_user_id`), dropdown (`area`) — colunas de **sistema** | A | confirmado via `PATCH /boards/items/{id}` (não via `/values/{column_id}`, que é a rota certa só para colunas customizadas); reconfirmado de forma independente (item `7650`) |
| Textos/números/e-mails/links/`board_relation`/`mirror` — colunas **customizadas** | B | criação da coluna bloqueada p/ token (`403`, requer login); a rota de `values` não exige login (só rejeitou por tipo de coluna, `400`, nas colunas de sistema testadas) — forte indício de que funciona; falta 1 coluna real (criada manualmente na Fase 1) para confirmação direta do payload |
| Subitens (aditivos Contratos) | A | criação nativa confirmada, inclusive sem `hierarchy_depth` habilitado via PATCH (irrelevante para o fluxo) |
| Arquivos (PDF Procon/Contratos) | B | upload binário bloqueado p/ token; anexo por link confirmado (`201`) — fallback via Drive/GCS |
| Updates/histórico (comentários) | A/B | criar/listar/excluir nativos; editar bloqueado mas não necessário (comentário é criado uma única vez na migração) |
| Conexões entre quadros (`board_relation`) | B | criação da coluna bloqueada (mesma causa-raiz do bloqueio de esquema); `/links` também bloqueado para leitura **e** escrita — o fluxo não pode depender dele; fallback: coluna criada 1x manualmente + tabela local de relações como reforço |
| Mirror | B | criação de coluna e `mirror-values` bloqueados; cópia/lookup no sync |
| Automações cross-board | B | nosso código |
| Evento de item criado (Controle) | A/B | `webhook` nativo confirmado (~1s de latência, sem retry demonstrado); polling+ETag como arquitetura resiliente principal |
| Busca por valor | B | índice local |
| Rastreabilidade de IDs | B | mapa local (`data/monday-sunday-map.json`) + coluna `text` "Monday ID" |
| `location` | B | → text |
| `formula` | C | 2 colunas |
| `time_tracking` | B/C | total em `number` + configuração manual |
| — | **D: nenhum** | nada bloqueante identificado; o esquema de colunas customizadas exige passo manual único por board, não trabalho recorrente do adapter |

**Decisão final: GO** para iniciar `sunday/client.py`. As três rodadas de teste
convergem no mesmo diagnóstico técnico: (1) CRUD de boards/grupos/itens/comentários e
anexos-por-link funciona nativamente; (2) as colunas de **sistema** do template têm
value confirmado via `PATCH /boards/items/{id}` — reconfirmado de forma independente e
reproduzível; (3) a automação `webhook` funciona nativamente; (4) o único ponto sem
demonstração empírica direta é o value de colunas **customizadas** (inclusive
`board_relation`/`mirror`), porque a criação da coluna é bloqueada para o token — mas a
mesma rota de `values` não rejeitou por permissão nenhuma das colunas testadas (só por
tipo, nas de sistema), o que é indício forte de que funcionará. Esse gap é resolvido com
um passo manual único por board (criar o esquema de colunas na Fase 1, ~146 colunas nos
8 boards integrados, sem recorrência por item) — exatamente o tipo de "complementação
manual residual" que a autorização desta tarefa definiu como aceitável para o GO, e não
uma ausência de fallback (que seria o critério de bloqueio). Nenhum item da matriz ficou
em classe D.

**V1 (adapter imediato, `sunday/client.py`):**
- Autenticação (`X-Sunday-Token`) e preflight (`GET /boards/{id}`, `GET
  /workspaces/{id}`) para validar o vínculo board↔workspace antes de escrever.
- CRUD de grupos/itens: `POST /boards/{id}/groups`, `POST /boards/{id}/items` (com
  `group_id`/`parent_item_id` já corretos na criação — mover depois exige login),
  `PATCH /boards/items/{id}` (nome/descrição e campos de sistema — pessoas, data,
  dropdown), `PATCH /boards/items/{id}/status`, `DELETE /boards/items/{id}`.
- Leitura/escrita de `values` em colunas **customizadas** pré-criadas manualmente na
  Fase 1, via `/boards/items/{id}/values/{columnId}` — inclui `board_relation` e
  `mirror`; confirmar o payload exato assim que existir 1 coluna real de cada tipo.
- Comentários (criação/leitura/exclusão) e anexos por link (upload real via Drive/GCS).
- Cache + polling com `ETag` (T9), índice local de dedup (T10), mapa de IDs (T13).

**V2 (pode ficar para depois):**
- Automação `webhook` como upgrade de latência do polling (já confirmada funcional;
  sem garantia de retry demonstrada — tratar como fire-and-forget).
- Espelhos (`mirror`) por lookup no nosso código.
- Views/filtros.
- Aprovações.
- Preservação de `time_tracking` em coluna `number`.

**MANUAL (tratado durante a migração, fora do adapter):**
- Criação do esquema de colunas customizadas por board (~146 colunas nos 8 boards
  integrados) — passo único via login humano na UI do Sunday na Fase 1, incluindo
  `board_relation`/`mirror` e as opções de `status`/`dropdown` extras.
- Renomear grupos e ajustar configurações de board (ex. `hierarchy_depth`,
  `capabilities`), se necessário — feito uma vez, na criação/setup.
- Fórmulas (2 colunas: "saving"/"Saved").
- Revisão de views/membros por board.
- Cronômetro de `time_tracking` (config única da coluna, se quiserem recomeçar a
  cronometrar no Sunday).

### F0.15 Reteste de values e board_relation em colunas pré-configuradas (2026-08-11)

> Fecha o único ponto sem demonstração empírica do F0.14: escrita/leitura de `values`
> em colunas **customizadas** previamente criadas (schema manual — decisão de
> arquitetura: a API não precisa criar/alterar colunas; o adapter só manipula dados).
> Sandbox autorizado: boards `80` (principal) e `81` (RELATION), workspace 22. Nenhuma
> escrita fora deles; nada foi alterado no Monday. Scripts:
> `scripts/sunday_fase0_values_retest.py` (T1–T10) e
> `scripts/sunday_fase0_values_retest_probe.py` (sonda complementar de status, people e
> relação múltipla). Relatório sanitizado:
> `docs/sunday-fase0-values-retest-2026-08-11.json`.

**Validação inicial.** `SUNDAY_API_TOKEN` e `SUNDAY_API_URL` presentes no ambiente;
`GET /boards/80` e `GET /boards/81` confirmaram os nomes exatos dos dois sandboxes antes
de qualquer escrita. As 8 colunas pedidas existem no board 80 (títulos com variação de
caixa, casados por normalização), **com duas ressalvas estruturais**:

1. Quatro das oito "colunas TESTE" são na verdade as colunas de **sistema** do template
   renomeadas (Texto = `name`, Status = `status`, Data = `target_date`, Responsável =
   `owner`). Isso fez o reteste exercitar **as duas rotas de escrita** (values para
   customizadas, `PATCH` do item para as de sistema) — resultado igualmente conclusivo.
2. A coluna **TESTE - Relação está configurada para o board errado**:
   `settings.source_board_id = "79"` — e o board 79 é **"Legal - Seguros" (produção)**,
   não o 81. Nenhuma escrita ou referência a itens do board 79 foi feita; a relação foi
   testada apontando para itens criados no board 81 e a API **aceitou mesmo assim** (ver
   T10). Corrigir a configuração da coluna para o board 81 manualmente.

**T1 — Column IDs do board 80 (nome → column_id → type → settings):**

| Coluna (label real) | column_id | key | type | sistema? | settings |
|---|---|---|---|---|---|
| TESTE - texto | `443` | `name` | `text` | sim | `{}` |
| TESTE - Número | `453` | `teste_numero` | `number` | não | `{}` |
| Teste - Status | `444` | `status` | `status` | sim | `{"use_board_status_set": true}` |
| teste - Data | `446` | `target_date` | `date` | sim | `{"include_time": false}` |
| teste - Responsável | `445` | `owner` | `people` | sim | `{"multi": false}` |
| Teste - LINK | `454` | `teste_link` | `link` | não | `{}` |
| TESTE - CHECKBOX | `455` | `teste_checkbox` | `checkbox` | não | `{}` |
| TESTE - RELAÇÃO | `456` | `teste_relacao` | `board_relation` | não | `{"source_board_id": "79"}` ⚠ deveria ser `"81"` |

**T2 — Item fictício.** `POST /boards/80/items {"name": "TESTE VALUES API - PODE
EXCLUIR"}` → `201`, item `7659`. Itens deixados no sandbox para conferência (todos
"PODE EXCLUIR"): `7659` e `7663` no board 80; `7660` e `7664` no board 81 (além do
`7654`, remanescente homônimo da rodada anterior, reutilizado pela sonda).

**T3–T10 — Resultados por tipo (payload enviado, HTTP e formato devolvido pelo GET):**

| Teste | Coluna | Rota que funcionou | Payload aceito | HTTP | GET devolve | Round-trip |
|---|---|---|---|---|---|---|
| T3 Texto | `443` (sistema `name`) | `PATCH /boards/items/{id}` | `{"name": "Teste Sunday API"}` | 200 | `name: "Teste Sunday API"` (idêntico) | ✅ |
| T4 Número | `453` (custom) | `PATCH .../values/453` | `{"value": 12345}` (número JSON) | 200 | `value: 12345` (número JSON, sem coerção p/ string) | ✅ |
| T5 Status | `444` (sistema) | `PATCH /boards/items/{id}/status` | `{"status": "follow_up", "cascade": false}` (key real do `status_set` do board: `to_do`/`follow_up`/`done`) | 200 | `status: "follow_up"` | ✅ |
| T6 Data | `446` (sistema `target_date`) | `PATCH /boards/items/{id}` | `{"target_date": "2026-01-15"}` | 200 | `"2026-01-15T12:00:00.000Z"` (normaliza para meio-dia UTC) | ✅ |
| T7 Checkbox | `455` (custom) | `PATCH .../values/455` | `{"value": true}` e depois `{"value": false}` | 200/200 | `true` e depois `false` (booleano JSON) | ✅ |
| T8 Link | `454` (custom) | `PATCH .../values/454` | `{"value": "https://example.com/teste-sunday-api"}` (string simples) | 200 | a mesma string | ✅ |
| T9 People | `445` (sistema `owner`) | `PATCH /boards/items/{id}` | `{"owner_user_id": "<id do /auth/me>"}` | 200 | `owner_user_id` preenchido | ⚠ parcial (ver abaixo) |
| T10 Relação | `456` (custom `board_relation`) | `PATCH .../values/456` | `{"value": "7660"}` (string), `{"value": ["7654","7664"]}` (lista) e `{"value": null}` (limpar) | 200 nos três | o(s) `item_id`(s) exatamente como gravados; `null` após limpar | ✅ |

Erros documentados (sanitizados):

- `PATCH /boards/items/{id}/values/{col}` nas 4 colunas de **sistema** → `400
  {"message": "System columns são atualizadas via PATCH /boards/items/:id.", "error":
  "Bad Request"}` — mensagem de negócio, não de permissão (comportamento já visto no
  follow-up do F0.14, agora confirmado como **a única exceção**: nas colunas
  customizadas a mesma rota funciona).
- `PATCH /boards/items/{id}` com `{"status": ...}` → `200` porém **ignorado em
  silêncio** (status só muda pela rota dedicada `/status`). Mesmo padrão já conhecido de
  `group_id` e `assignee_user_ids`.
- T9 people: `values/445` com `"<id>"` e `["<id>"]` → `400` (coluna de sistema). Pela
  rota do item, `{"owner_user_id": <id do /auth/me>}` → `200` com `updated_at`
  avançando; porém o owner **já nasce igual ao criador** (dono do token), então com um
  único usuário disponível não dá para observar a troca de valor; `{"owner_user_id":
  null}` e `{"assignee_user_ids": [...]}` são ignorados em silêncio (200 sem efeito).
  Nenhum `user_id` foi inventado. Não bloqueante: o de-para e-mail→`user_id` virá de
  `GET /users/directory` (200, F0.14) e a atribuição definitiva se confirma na Fase 1
  com um segundo usuário real.

**T10 — Respostas objetivas sobre board_relation:**

1. **O Sunday aceitou gravar a relação?** Sim — `200` na primeira tentativa, payload
   mínimo `{"value": "<item_id>"}`; aceita também **lista** de ids (one-to-many, caso
   Controle → Contratos) e `null` para desfazer.
2. **O GET devolve o target item_id?** Sim — `GET /boards/items/{id}/values` devolve
   `{"column_id": "456", "value": "7660"}` (ou a lista), exatamente como gravado.
3. **O target board pode ser identificado?** Indiretamente: o value guarda **só** o
   item_id; o board-alvo vem de `settings.source_board_id` da coluna (config manual).
   Atenção: a API **não valida** o value contra essa config — aceitou ids do board 81
   com a coluna apontando para o 79. A integridade referencial é responsabilidade do
   adapter (validar o id contra o board esperado antes de gravar).
4. **Reconstruir source → target sem `/boards/{id}/links`?** Sim — basta
   `GET /boards/items/{id}/values`; `/links` (403 para o token) é dispensável.
5. **Manter a relação no futuro só com endpoints normais?** Sim — criar, trocar
   (regravar o value), adicionar múltiplos (lista) e desfazer (`null`) funcionam pela
   rota normal de values.

**Conclusão sobre fallback:** a tabela local de relações (monday/sunday × source/target)
**não é necessária** como mecanismo primário — a relação nativa funciona por values.
Segue recomendada apenas como registro de auditoria durante a migração (de-para
Monday→Sunday, T13), não como fonte de verdade em produção.

**O que funciona / o que não funciona (values):**

- Funcionam nativamente: número, checkbox, link, **board_relation** (single, lista,
  limpar) via `/values/{column_id}`; texto (`name`), data (`target_date`) e dropdown
  (`area`, F0.14) via `PATCH /boards/items/{id}`; status via `PATCH
  /boards/items/{id}/status`.
- Funcionam com ressalva: people (`owner_user_id` aceito pela rota do item; troca de
  valor não observável com um único usuário; `assignee_user_ids` ignorado — confirmar
  na Fase 1 com segundo usuário).
- Não testados por não existirem colunas customizadas desses tipos no sandbox: `text`
  custom (inferido pelas demais customizadas), `long_text`, `email`, `phone`,
  `dropdown`/`status` customizadas com options próprias, `mirror` (leitura já sabida
  403 para token — fallback lookup no código). Nenhum deles muda a decisão: a rota de
  values para colunas customizadas está comprovada em 4 tipos, incluindo o mais crítico
  (`board_relation`).

**Matriz Go/No-Go atualizada (A nativo · B fallback/transformação · C manual aceitável ·
D bloqueante):**

| Requisito | Classe | Mudança vs F0.14 |
|---|---|---|
| Criar/listar/alterar/excluir itens; status de sistema | A | mantém |
| Values de colunas customizadas (número, checkbox, link) | **A** | era B (indício) → **confirmado empiricamente** |
| Values de colunas de sistema (texto/nome, data, dropdown, status) | A | mantém (rotas dedicadas confirmadas de novo) |
| `board_relation` (Prazos→Processos; Audiências→Processos; Controle→Contratos) | **A** | era B (fallback) → **nativo confirmado** (single + lista + null); ressalvas: config manual da coluna e validação de board a cargo do adapter |
| People | B | owner pela rota do item aceito; confirmação final de troca exige 2º usuário (Fase 1); não bloqueante |
| Criação/alteração de schema (colunas) via API | **C** | decisão de arquitetura: schema manual no Sunday; dados via `sunday/client.py` — **não bloqueante** |
| Arquivos | B | mantém (Drive/GCS → anexo por link) |
| Mirror | B/C | mantém (lookup/cópia no código) |
| Busca | B | mantém (cache/índice local) |
| Webhook | opcional | mantém (polling é a arquitetura principal) |
| Comentários / identificação de registros | A | mantém |
| — | **D: nenhum** | — |

**Decisão final: GO** para implementar `sunday/client.py`. Todos os essenciais do
critério de decisão estão confirmados empiricamente: criação/leitura/alteração/exclusão
de item; escrita/leitura de values em colunas existentes (customizadas via
`/values/{column_id}`; de sistema via `PATCH` do item e `/status`); comentários;
identificação de registros; e **relações nativas por values** (sem depender de
`/links` nem de tabela local). A impossibilidade de criar schema pela API fica
classificada como **C — configuração manual aceitável**, conforme a decisão de
arquitetura. Pendências não bloqueantes para a Fase 1: corrigir manualmente o
`source_board_id` da coluna de relação do sandbox (hoje aponta para o board 79 —
produção); confirmar people com um segundo usuário; criar 1 coluna customizada de cada
tipo restante (`text`, `long_text`, `email`, `status`/`dropdown` com options) para
fixar os payloads no adapter. Nada de `sunday/client.py`, workflows ou migração de
dados reais foi implementado nesta rodada.

---

## Fase 1 — Sunday Client V1 (2026-08-11)

> Implementação do cliente genérico autorizada após o GO da Fase 0. Escopo desta fase:
> **somente** o client + testes automatizados. Nenhum workflow foi alterado, nenhuma
> integração Monday foi tocada, nenhum dado foi migrado, nenhum board real foi alterado.

### Arquitetura

Pacote `src/classificacao_procons/sunday/`:

- `http.py` — camada HTTP centralizada: `SundayConfig` (lê `SUNDAY_API_URL` +
  `SUNDAY_API_TOKEN`; token com `repr=False`), `SundayHttp` (base URL, header
  `X-Sunday-Token`, timeout, JSON, ETag/`If-None-Match`/304, mapeamento de erros) e
  transporte **injetável** (`urllib` por padrão; fake nos testes). Retry: apenas `GET`
  em 5xx (máx. 3 tentativas, backoff exponencial); POST/PATCH/DELETE **nunca** são
  repetidos em silêncio (risco de duplicidade).
- `errors.py` — exceções: `SundayConfigError`, `SundayAuthError` (401),
  `SundayForbiddenError` (403), `SundayNotFoundError` (404), `SundayValidationError`
  (400/payload), `SundayConflictError` (409/422), `SundayHTTPError` (genérico/rede),
  `SundayRelationIntegrityError` (relação com board errado) e `SundayVerifyError`
  (2xx sem persistir). Mensagens carregam método, caminho, status e a mensagem de
  negócio da API — nunca token/headers.
- `models.py` — dataclasses congeladas com `raw` preservando campos não modelados:
  `Board` (+`status_set`), `Group`, `Column` (+`settings.source_board_id`), `Item`
  (campos de sistema + `updated_at`), `ItemValue` (tipo JSON preservado), `Comment`,
  `Attachment`, `SundayUser`, `Workspace`/`WorkspaceBoardRef` (separa `link_id` de
  `board_id` — F0.13), `ItemsResult`/`ValuesResult` (ETag/304) e helpers
  `parse_sunday_date`/`format_target_date`/`normalize_relation_value`. IDs sempre
  strings.
- `client.py` — `SundayClient`, genérico e sem hardcode de boards reais.
- `tracking.py` — `MigrationRecord`/`MigrationStatus` para a futura camada de
  migração (fora do client de propósito).

### Métodos e endpoints encapsulados (todos empíricos, F0.13–F0.15)

| Método | Endpoint |
|---|---|
| `get_me()` | `GET /auth/me` |
| `list_users_directory()` | `GET /users/directory` |
| `list_boards()` / `get_board(id)` | `GET /boards` / `GET /boards/{id}` (cache) |
| `get_workspace(id)` | `GET /workspaces/{id}` |
| `list_groups` / `create_group` | `GET`/`POST /boards/{id}/groups` |
| `list_columns` / `get_column` | `GET /boards/{id}/columns` (cache por board) |
| `list_items(etag=…)` | `GET /boards/{id}/items` (+`If-None-Match` → 304) |
| `get_item` | filtro sobre a listagem (GET individual não existe — 404) |
| `create_item` | `POST /boards/{id}/items` (`group_id`/`parent_item_id`/…) |
| `update_item(verify=…)` | `PATCH /boards/items/{id}` (name/description/target_date/owner_user_id/area) |
| `delete_item` | `DELETE /boards/items/{id}` |
| `set_status(verify=…)` | `PATCH /boards/items/{id}/status` (rota dedicada) |
| `list_values(etag=…)` / `get_value` | `GET /boards/items/{id}/values` |
| `set_custom_value(verify=…)` | `PATCH /boards/items/{id}/values/{col}` |
| `set_relation(verify=…)` / `get_relation` | idem values (board_relation) |
| `list_comments` / `add_comment` / `delete_comment` | `GET`/`POST /boards/items/{id}/comments`, `DELETE /boards/comments/{id}` |
| `list_attachments` / `add_link_attachment` | `GET /boards/items/{id}/attachments`, `POST …/attachments/link` |

### Decisões de segurança e comportamento

- **Token**: só existe no header montado no envio; fora de `repr`, exceções, logs e
  relatórios (testado).
- **Status**: `update_item` **não tem** parâmetro `status` (o PATCH genérico devolve
  200 e ignora — F0.15). `set_status()` valida a key contra o `status_set` do board e
  aceita `verify=True` (write→read→compare).
- **Campos de sistema** (`name`, `status`, `target_date`, `owner`, `area`): nunca via
  rota de values — o client rejeita antes (a API devolveria 400 de negócio). `area` só
  é enviada quando explicitamente informada (coluna estrutural; desconhecê-la não
  impede criar/editar item).
- **Datas**: escrita `YYYY-MM-DD`; a API normaliza para meio-dia UTC
  (`…T12:00:00.000Z`). `parse_sunday_date` extrai o dia do negócio sem conversão de
  fuso (que poderia mudar o dia); `verify` de `target_date` compara só a parte de
  data. Coberto por testes.
- **People**: `owner_user_id` implementado conforme contrato aceito; troca efetiva
  entre usuários distintos segue **não totalmente validada** (1 usuário na F0.15) —
  nenhuma lógica de domínio deve depender disso na V1.
- **board_relation e integridade**: a API **não valida** o board do item relacionado
  (aceitou item do board 81 em coluna configurada para o 79). `set_relation()` exige
  `expected_target_board_id`, confere `type == board_relation` e
  `settings.source_board_id` **antes** de gravar; divergência → 
  `SundayRelationIntegrityError` sem nenhuma chamada de escrita. Suporta 1 alvo,
  lista e remoção (`null`); leitura reconstrói a relação só por values (sem `/links`).
- **Verify-after-write**: opt-in (`verify=True`) em `update_item`, `set_status`,
  `set_custom_value` e `set_relation` — HTTP 200 isolado não é prova de persistência.
- **Schema manual (classe C)**: o client **não** cria/altera/exclui colunas, mirror,
  formula, time_tracking nem views. `/boards/search` não é usado (dedup ficará em
  cache/índice local da camada superior; `updated_at` preservado nos modelos).
- **Anexos**: só por link na V1 (upload binário é 403 para tokens); arquitetura:
  Drive/GCS → URL → `attachments/link`.
- **Comentários**: criar/listar/excluir; edição não exposta (403). O client recebe o
  `body` pronto — transformações de migração (ex.: `[Monday · autor · data]`) ficam na
  camada de migração.

### Testes

- `tests/test_sunday_client.py` — 49 testes unitários com transporte fake (nenhuma
  chamada real): header/sanitização do token, IDs como strings, CRUD, status dedicado
  (+ proibição no PATCH genérico + verify falhando quando 200 não persiste), custom
  values (string/número/booleano/null/lista, preservação de tipo, releitura), relação
  1:1/1:N/remoção/verify/board errado/coluna sem config, comentários, anexo por link,
  ETag/If-None-Match/304 (items e values), erros 400/401/403/404, normalização de
  datas e vínculo workspace-board.
- `tests/test_sunday_integration.py` — smoke **opt-in** (`SUNDAY_INTEGRATION_SANDBOX=1`
  + secrets), somente leitura nos sandboxes 80/81; nunca roda no pytest padrão.

### Limitações conhecidas (ficam para V2/fases seguintes)

Upload binário; automação `webhook`; mirror por lookup; views; aprovações; troca de
owner com 2º usuário; payloads de colunas customizadas `long_text`/`email`/`phone`/
`dropdown`-com-options (inferidos, não exercitados — fixar quando as colunas forem
criadas nos boards); seletor de backend `monday|sunday|dual` e o cron de Contratos
(usarão as primitivas de ETag/cache do client).

---

## Fase 2 — Inventário, Mapping e Dry-run (2026-08-11)

> Executada 100% em LEITURA: inventário real do Monday (GraphQL, itens digeridos de
> forma sanitizada — sem nomes, CPF, textos ou conteúdo de updates), schema real do
> Sunday (snapshot autenticado da F0.13; regerável ao vivo com `--refresh-sunday`) e
> dry-run classificando item a item. Nenhuma escrita em Monday ou Sunday. Board
> **Acessos não foi lido** (fora do escopo). Artefatos: relatório agregado
> `docs/sunday-migration-dry-run-2026-08-11.json`, identidades hasheadas
> `docs/monday-user-identities-2026-08-11.json`; o inventário completo sanitizado
> (2,5 MB) não é versionado — regerar com
> `python scripts/sunday_migration_dry_run.py --dump-monday-inventory <path>`.
> Ferramentas: `src/classificacao_procons/migration/` + `scripts/sunday_migration_dry_run.py`.

### F2.1 Inventário Monday real (Onda 1)

| Board | Total | Recorte | SKIP (concluídos antigos) | Itens c/ arquivo (recorte) | Arquivos (board) | MB | Itens c/ updates (recorte) | Updates (board) | Subitens (recorte) | Conexões (recorte) | Pessoas |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Procons | 457 | 193 | 264 | 29 | 1.724 | 840 | 193 | 1.696 | 0 | 0 | 0 |
| Prazos | 878 | 175 | 703 | 1 | 21 | 117 | 165 | ≥2.999 | 0 | 35 | 3 |
| Audiências | 120 | 41 | 79 | 19 | 38 | 230 | 34 | 98 | 0 | 20 | 9 |
| Processos Judiciais | 155 | 124 | 31 | 74 | 528 | 974 | 75 | 510 | 0 | 0 | 6 |
| Processos Trabalhista | 24 | 10 | 14 | 0 | 0 | 0 | 4 | 26 | 0 | 0 | 0 |
| KPI - Processos Consumidores | 31 | 0 | 31 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Controle Assinaturas | 1.607 | 553 | 1.054 | 0 | 0 | 0 | 327 | 797 | 0 | 2 | 10 |
| Contratos | 1.119 | 963 | 156 | 110 | 131 | 354 | 306 | 299 | 104 | 0 | 48 |
| **Total** | **4.391** | **2.059** (+1 pull-in = **2.060**) | 2.331 | 233 | 2.442 | ~2.500 | 1.104 | ≥6.425 | 104 | 57 | 58 |

Semântica real de "concluído" (derivada dos grupos/status reais, codificada em
`migration/mappings.py`): grupos de arquivo (anos "2023…2026", "Assinados",
"Recusado", "Encerrados", "Arquivado") e labels terminais na coluna principal
("Feito", "Cancelada", "Baixado", "Respondido", "Assinado", "Encerrado"…); no board
Contratos a coluna de conclusão é **Vigência** ("Não Vigente" = concluído — override
explícito). Recorte: abertos sempre + criados nos últimos 12 meses + **pull-in** de
alvos de relação (1 item de Processos Judiciais puxado por Audiências).

Nota importante da coleta: o campo `value` genérico da API do Monday volta **vazio**
para colunas de conexão na versão 2024-10 — as conexões reais só aparecem via
fragmento tipado `BoardRelationValue.linked_item_ids` (corrigido no inventário; sem
isso as relações pareceriam inexistentes).

### F2.2 Matriz board → board

| Monday (id) | Sunday (id) | Domínio | Confiança | Observação |
|---|---|---|---|---|
| Procons (4944254220) | **TARGET A CRIAR** | procon | ALTA | schema proposto nas tabelas F2.3 |
| Prazos (3961072966) | **TARGET A CRIAR** | juridico | ALTA | — |
| Audiências (4443295406) | Legal - Audiências (72) | juridico | MÉDIA | candidato natural; só tem as 5 colunas de sistema |
| Processos Judiciais (5343921475) | **TARGET A CRIAR** | juridico | ALTA | quadro-mestre; alvo de relações |
| Processos Trabalhista (4443297481) | **TARGET A CRIAR** | juridico | ALTA | — |
| KPI - Processos Consumidores (5563754463) | **TARGET A CRIAR** | juridico | ALTA | recorte = 0 itens; ver decisão em F2.10 |
| Controle Assinaturas (5301515799) | Legal - Controle de Assinaturas - Jan & Luciano (77) | contratos | MÉDIA | candidato natural; schema a completar |
| Contratos (5385471914) | **TARGET A CRIAR** | contratos | ALTA | alvo de relações e subitens (aditivos) |

Boards administrativos do workspace Legal (Certidões, Seguros, Marcas etc.) ficam
fora da Onda 1, conforme decisão. "Legal - Seguros" (79) e "Legal - Acessos" (78) do
Sunday **não** são alvos desta onda.

### F2.3 Mapping de colunas por board

Estratégias: DIRETO · TRANSFORMAÇÃO · CONFIGURAR MANUALMENTE · NÃO MIGRAR · DERIVADO
PELO CÓDIGO. Colunas de status viram colunas custom com options 1:1 (keys slug);
`Name` vira o campo de sistema `name`; toda tabela abaixo vem do schema real lido
hoje. Cada board recebe adicionalmente a coluna técnica **“Monday ID” (text)** para
rastreabilidade/idempotência.

**Procons** (Monday `4944254220` → Sunday `A CRIAR`):

| Coluna Monday (`id`) | Tipo | Estratégia | Alvo Sunday |
|---|---|---|---|
| Name (`name`) | name | DIRETO | name (campo de sistema) |
| Subelementos (`subelementos_mkm7khms`) | subtasks | DERIVADO PELO CÓDIGO | subitens nativos (parent_item_id) |
| Procon/Órgão (`texto`) | text | DIRETO | text |
| Origem (`status_1`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| CPF (`long_text_mkxb3zgq`) | long_text | DIRETO | long_text |
| Notificação Procon (`arquivos`) | file | TRANSFORMAÇÃO | attachments/link |
| CIP/FA (`texto1`) | text | DIRETO | text |
| Data da Reclamação (`data`) | date | DIRETO | date |
| Prazo resposta SAC (`data30`) | date | DIRETO | date |
| Prazo Resposta Jurídico (`data3`) | date | DIRETO | date |
| Data da Resposta Legal/Baixa (`data2`) | date | DIRETO | date |
| Houve Cancelamento de Assinatura? (`color_mknz9dwg`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Status (`status8`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Docs SAC (`arquivos8`) | file | TRANSFORMAÇÃO | attachments/link |
| Observações/Histórico (`long_text`) | long_text | DIRETO | long_text |
| Causa 1 (`status_11`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Causa 2 (se houver) (`dup__of_causa_1`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Causa 3 (se houver) (`dup__of_causa_2`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Causa 4 (se houver) (`color`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Gerou Processo Administrativo (`status_118`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Prazo Resposta Processo Administrativo (`date_mkxcbdff`) | date | DIRETO | date |
| Processo Administrativo Respondido (`color_mkxc8v59`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Já está na black list? (`color_mky56w54`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |

**Prazos** (Monday `3961072966` → Sunday `A CRIAR`):

| Coluna Monday (`id`) | Tipo | Estratégia | Alvo Sunday |
|---|---|---|---|
| Name (`name`) | name | DIRETO | name (campo de sistema) |
| Subelementos (`subelementos`) | subtasks | DERIVADO PELO CÓDIGO | subitens nativos (parent_item_id) |
| Número Processo (`texto`) | text | DIRETO | text |
| Processo Administrativo (`status_1`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Status (`status`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Data (`data`) | date | DIRETO | date |
| Fatal (`dup__of_data__1`) | date | DIRETO | date |
| Pessoa (`person`) | people | TRANSFORMAÇÃO | people (owner) via de-para de usuários |
| Arquivos (`arquivos6`) | file | TRANSFORMAÇÃO | attachments/link |
| Controle de tempo (`controle_de_tempo`) | time_tracking | TRANSFORMAÇÃO | number (horas acumuladas) |
| Processos Consumidores (`conectar_quadros`) | board_relation | TRANSFORMAÇÃO | board_relation (values) + mapa de IDs |

**Audiências** (Monday `4443295406` → Sunday `72`):

| Coluna Monday (`id`) | Tipo | Estratégia | Alvo Sunday |
|---|---|---|---|
| Name (`name`) | name | DIRETO | name (campo de sistema) |
| Subelementos (`subelementos__1`) | subtasks | DERIVADO PELO CÓDIGO | subitens nativos (parent_item_id) |
| Data (`data`) | date | DIRETO | date ✓existe |
| Local (`local`) | location | TRANSFORMAÇÃO | text |
| Presencial ou Virtual (`status_1`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Responsável por comparecer (`color`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Status documentos (`status3`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Link Audiência (se virtual) (`link`) | link | DIRETO | link |
| Processo/Procon (`status8`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Arquivos (`arquivos`) | file | TRANSFORMAÇÃO | attachments/link |
| Pessoas (`pessoas7`) | people | TRANSFORMAÇÃO | people (owner) via de-para de usuários |
| Status (`status5`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) ✓existe |
| E-mail (`e_mail7`) | email | DIRETO | email |
| Processos Judiciais (`conectar_quadros__1`) | board_relation | TRANSFORMAÇÃO | board_relation (values) + mapa de IDs |
| Processos Judiciais (`conectar_quadros8__1`) | board_relation | TRANSFORMAÇÃO | board_relation (values) + mapa de IDs |
| Número do Processo (`n_meros6__1`) | long_text | DIRETO | long_text |
| Orientações de Audiência (`texto__1`) | text | DIRETO | text |

**Processos Judiciais** (Monday `5343921475` → Sunday `A CRIAR`):

| Coluna Monday (`id`) | Tipo | Estratégia | Alvo Sunday |
|---|---|---|---|
| Name (`name`) | name | DIRETO | name (campo de sistema) |
| Subelementos (`subelementos__1`) | subtasks | DERIVADO PELO CÓDIGO | subitens nativos (parent_item_id) |
| Processo relacionado a (`status85`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| SAC (`pessoas`) | people | TRANSFORMAÇÃO | people (owner) via de-para de usuários |
| Tipo de Ação (`texto2`) | text | DIRETO | text |
| Data de Distribuição (`data99`) | date | DIRETO | date |
| Sistema (`status_15__1`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Órgão/JEC (`status8`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| TJ (`status3`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Número (`n_mero`) | long_text | DIRETO | long_text |
| Cópia do Processo (CONSUMIDOR) (`arquivos`) | file | TRANSFORMAÇÃO | attachments/link |
| Cópia do Processo (NÃO CONSUMIDOR) (`file__1`) | file | TRANSFORMAÇÃO | attachments/link |
| Prazo Resposta SAC (`data9`) | date | DIRETO | date |
| Observações/Históricos (`long_text`) | long_text | DIRETO | long_text |
| Houve Cancelamento de Assinatura? (`color_mknz5qfs`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Documentos SAC (`arquivos2`) | file | TRANSFORMAÇÃO | attachments/link |
| Prazo Resposta Legal (`data0`) | date | DIRETO | date |
| Audiência (`status_1__1`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Data ad Audiência (`data9__1`) | date | DIRETO | date |
| Local da Audiência (`local__1`) | location | TRANSFORMAÇÃO | text |
| Pessoa responsável pela Audiência (`pessoas__1`) | people | TRANSFORMAÇÃO | people (owner) via de-para de usuários |
| E-mail Metajur/LBZ (se houver) (`e_mail__1`) | email | DIRETO | email |
| valor da causa (`n_meros6`) | numbers | DIRETO | number |
| Movimentações (`texto_longo`) | long_text | DIRETO | long_text |
| Risco (`status9`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Provisão B4A (`n_meros`) | numbers | DIRETO | number |
| Provisão MMKT (`n_meros6__1`) | numbers | DIRETO | number |
| Depósito B4A (`n_meros__1`) | numbers | DIRETO | number |
| Depósito MMKT (`n_meros68`) | numbers | DIRETO | number |
| Pagamentos B4A (`n_meros1__1`) | numbers | DIRETO | number |
| Pagamentos MMKT (`n_meros5__1`) | numbers | DIRETO | number |
| condenação (`n_meros1`) | numbers | DIRETO | number |
| saving (`f_rmula`) | formula | CONFIGURAR MANUALMENTE | formula (expressão do Sunday) |
| Problema Principal (se aplicável) (`status92`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Status (`status2`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Decisão Judicial (`status_10__1`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |

**Processos Trabalhista** (Monday `4443297481` → Sunday `A CRIAR`):

| Coluna Monday (`id`) | Tipo | Estratégia | Alvo Sunday |
|---|---|---|---|
| Name (`name`) | name | DIRETO | name (campo de sistema) |
| Status (`status1`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Tipo de Processo (`status0`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Parte Ré (`texto8`) | text | DIRETO | text |
| Nº.: de Processo (`texto`) | text | DIRETO | text |
| Local de Origem (`local`) | location | TRANSFORMAÇÃO | text |
| Situação Atual (`texto6`) | text | DIRETO | text |
| Valor da Causa (`n_meros`) | numbers | DIRETO | number |
| Data de Distribuição (`data`) | date | DIRETO | date |
| Risco (`status`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Depósito/Pagamento (`n_meros1`) | numbers | DIRETO | number |
| Provisão (`n_meros9`) | numbers | DIRETO | number |
| Vara de Origem (`texto88`) | text | DIRETO | text |
| Saved (`f_rmula`) | formula | CONFIGURAR MANUALMENTE | formula (expressão do Sunday) |
| Forma de Contratação (`status_1__1`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |

**KPI - Processos Consumidores** (Monday `5563754463` → Sunday `A CRIAR`):

| Coluna Monday (`id`) | Tipo | Estratégia | Alvo Sunday |
|---|---|---|---|
| Name (`name`) | name | DIRETO | name (campo de sistema) |
| Estado (`status`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Ré (`status_1`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Data Ajuizamento (`data`) | date | DIRETO | date |
| Número do Processo (`texto_longo`) | long_text | DIRETO | long_text |
| Causa 1 (`status_14`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Causa 2 (`dup__of_causa_19`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Causa 3 (`dup__of_causa_2`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Situação (`status_160`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Data da Decisão (`data2`) | date | DIRETO | date |
| Resultado (`status_11`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Valor da Cusa (`n_meros`) | numbers | DIRETO | number |
| Provisão (`n_meros15`) | numbers | DIRETO | number |
| Valor da Condenação (`n_meros_1`) | numbers | DIRETO | number |
| Valor Pago (`n_meros0`) | numbers | DIRETO | number |
| Saving (`n_meros1`) | numbers | DIRETO | number |

**Controle Assinaturas** (Monday `5301515799` → Sunday `77`):

| Coluna Monday (`id`) | Tipo | Estratégia | Alvo Sunday |
|---|---|---|---|
| Name (`name`) | name | DIRETO | name (campo de sistema) |
| Subelementos (`subelementos`) | subtasks | DERIVADO PELO CÓDIGO | subitens nativos (parent_item_id) |
| Status (`status`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) ✓existe |
| Priority (`priority`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Data de Inclusão (na Plataforma) (`data`) | date | DIRETO | date |
| Até quando assinar (`data2`) | date | DIRETO | date |
| Data de Assinatura (`data0`) | date | DIRETO | date |
| Link Contrato Assinado (SOMENTE se envolver o Jan) (`link`) | link | DIRETO | link |
| Controle de tempo (`controle_de_tempo`) | time_tracking | TRANSFORMAÇÃO | number (horas acumuladas) |
| Nome da Plataforma (`texto`) | text | DIRETO | text |
| Link para assinatura (`long_text_mkvnwp6d`) | long_text | DIRETO | long_text |
| Assunto (`texto6`) | text | DIRETO | text |
| Quem Assina (`status_1`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Pessoas (`pessoas`) | people | TRANSFORMAÇÃO | people (owner) via de-para de usuários |
| Tipo (`status_1__1`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| link to Notificações Carol - Assinaturas Jan (`board_relation_mkqxj7gv`) | board_relation | TRANSFORMAÇÃO | board_relation (values) + mapa de IDs |
| Contrato relacionado (`board_relation_mm5ap90f`) | board_relation | TRANSFORMAÇÃO | board_relation (values) + mapa de IDs |

**Contratos** (Monday `5385471914` → Sunday `A CRIAR`):

| Coluna Monday (`id`) | Tipo | Estratégia | Alvo Sunday |
|---|---|---|---|
| Name (`name`) | name | DIRETO | name (campo de sistema) |
| Subelementos (`subelementos`) | subtasks | DERIVADO PELO CÓDIGO | subitens nativos (parent_item_id) |
| Empresa (`status1`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| CNPJ outra Parte (`texto8`) | text | DIRETO | text |
| Tipo de Contrato (`texto`) | text | DIRETO | text |
| Data do Contrato (`data`) | date | DIRETO | date |
| Término (`data0`) | date | DIRETO | date |
| Contrato (`arquivos`) | file | TRANSFORMAÇÃO | attachments/link |
| Vigência (`status`) | status | CONFIGURAR MANUALMENTE | status (coluna custom com options 1:1) |
| Observações (`texto_longo`) | long_text | DIRETO | long_text |
| Responsável (`pessoas3`) | people | TRANSFORMAÇÃO | people (owner) via de-para de usuários |


**Área (estrutural no Sunday):** nenhum domínio da Onda 1 tem coluna Monday
correspondente à Área. Decisão: **ignorar** (não preencher, não alterar, não
remover) em Prazos, Audiências, Processos, KPI e Trabalhista; em Procons e
Contratos/Controle, recomendação opcional de preencher com valor fixo por board
("Consumidor" / "Contratos") se o time quiser usar os filtros da home — decisão de
preferência, não técnica. Desconhecer Área não impede criação/edição (F0.15).

### F2.4 Status — de-para

Nenhum label fora do schema foi encontrado nos itens do recorte (zero
`MISSING_STATUS_MAPPING` no dry-run): o de-para é 1:1 label→option com key slug
determinística (ex.: "Aguardando Assinatura"→`aguardando_assinatura`, "Não
Vigente"→`nao_vigente`, 'Glam "Clube"'→`glam_clube`) — confiança ALTA, sem fuzzy
match. Labels reais por board (levantados dos itens): Procons Status =
Respondido/Baixado; Prazos Status = Não Iniciado/Em progresso/Feito/Cancelada;
Audiências Status = Em Andamento/Feito/Cancelada; Processos Judiciais Status = Em
Andamento/Suspenso/Encerrado; Trabalhista = Em andamento/Encerrado; Controle Status =
Aguardando Assinatura/Aguardando outros/Assinado/Recusado/Bloqueado - aguardando
providencia; Contratos Vigência = Vigente/Não Vigente (demais colunas de status nas
tabelas F2.3 seguem a mesma regra 1:1).

**Status de sistema do Sunday** (`to_do`/`follow_up`/`done`): derivado, não migrado —
`done` quando o item é "concluído" pela semântica F2.1; `to_do` caso contrário
(`follow_up` reservado para uso do time). O status de negócio fica na coluna custom.

### F2.5 People — de-para

58 usuários Monday distintos atribuídos nos boards da Onda 1: **28 com identidade
técnica resolvida** (ativos; hash sha256 do e-mail em
`docs/monday-user-identities-2026-08-11.json` — sem e-mail em claro) e **30 ids sem
cadastro visível** na API (usuários desativados/excluídos) → **SEM_MATCH**
definitivo, itens migram sem responsável (registrado no comentário de rastreio).
Matching com o Sunday: **pendente** — exige `GET /users/directory` (o secret não
existe nesta VM); o critério é **e-mail exato** = MATCH_EXATO; nome exato = apenas
candidato (MATCH_PROVÁVEL, nunca usado automaticamente). O dry-run demonstra o
impacto: sem de-para aprovado, 1.569 itens (76,2% do recorte) ficam MANUAL por
`MISSING_USER_MAPPING`; com de-para aprovado, 0.

### F2.6 Relações

Uso REAL (dados de hoje): **57 itens do recorte têm conexões** — Prazos→Processos
(35, coluna `conectar_quadros`), Audiências→Processos (20, colunas
`conectar_quadros__1`/`conectar_quadros8__1` — duas colunas homônimas "Processos
Judiciais"), Controle→Contratos (2, `board_relation_mm5ap90f`). A coluna "link to
Notificações Carol" do Controle aponta para board fora da Onda 1 → NÃO MIGRAR
(registrada em comentário). O vínculo dominante entre domínios continua sendo por
chave de negócio (CNJ, Autentique ID), como no código atual.

| Relação | Coluna Monday | Sunday source board | Coluna Sunday | `source_board_id` esperado |
|---|---|---|---|---|
| Prazos → Processos | `conectar_quadros` | board Prazos (a criar) | a criar | id do board Processos Judiciais (a criar) |
| Audiências → Processos (2×) | `conectar_quadros__1`, `conectar_quadros8__1` | 72 | a criar | id do board Processos Judiciais (a criar) |
| Controle → Contratos | `board_relation_mm5ap90f` | 77 | a criar | id do board Contratos (a criar) |

Validação de integridade: como o Sunday **não valida** o board do item relacionado
(F0.15 — o sandbox tinha coluna apontando para o board 79 de produção), o dry-run
marca `config_ok` por coluna e o `SundayClient.set_relation` exige
`expected_target_board_id`. Hoje: **nenhuma coluna de relação existe nos destinos** →
todas entram no checklist como CONFIGURAÇÃO MANUAL OBRIGATÓRIA ANTES DA MIGRAÇÃO,
com verificação automática do `source_board_id` no dry-run pós-checklist.

### F2.7 Arquivos

233 itens do recorte com arquivos; 2.442 assets (~2,5 GB) nos boards (inclui itens
fora do recorte). URLs de asset do Monday são autenticadas e **expiram** → todos os
arquivos exigem **materialização**: download do asset (token Monday) → upload ao
Drive (infra já usada por Procon/Contratos) → `attachments/link` no Sunday + coluna
`file_link` quando aplicável. Nenhum arquivo foi transferido nesta fase.

### F2.8 Updates / comentários

1.104 itens do recorte têm updates; volume por board ≥6.425 updates no total dos
boards (Prazos atingiu o teto de paginação da contagem — "≥"). Estratégia (Fase 3):
migrar updates dos itens do recorte como comments com corpo
`[Monday · autor · data]\n<texto>`, autoria técnica do robô; conteúdo dos updates
NÃO aparece em nenhum relatório desta fase (apenas contagens).

### F2.9 IDs, idempotência e rastreabilidade

Ledger persistente `data/monday-sunday-map.json` (JSON é a convenção de estado do
repositório — não há banco), dict indexado por `"{monday_board_id}:{monday_item_id}"`
com `sunday_board_id`, `sunday_item_id`, `domain`, `migration_status`
(pending/migrated/skipped/error), `migrated_at`, `source_updated_at`, `error`,
`attempts` (modelo `migration.models.LedgerRecord`). Garante reexecução sem
duplicar (lookup O(1) antes de criar), retomada após falha, reconciliação, rollback
lógico e auditoria. Redundância anti-perda: coluna **“Monday ID”** gravada em cada
item migrado (permite reconstruir o ledger inteiro lendo o Sunday) + comentário de
rastreio com origem. Escrita atômica (tmp+rename) e backup por execução.

### F2.10 Performance e recorte

- Leitura Monday (esta fase): ~60 requests, ~4 min para 4.391 itens (digest completo).
- Escrita futura (Fase 3, estimativa sobre o recorte): ~2.060 criações + ~8.000
  values + ~4.000 comments (updates dos itens do recorte) + ~500 anexos + releituras
  de verify por board ≈ **15–25 mil requests**; a 3–5 req/s com backoff ≈ **1,5–3 h**
  total, executável board a board com ledger (retomável). Rate limit do Sunday não é
  publicado — usar lotes moderados + backoff em 429/5xx.
- Padrão obrigatório de leitura no Sunday: **snapshot do board** (1 request) + cache/
  índice em memória com lookup O(1) por id/chave — `get_item()` nunca em loop (regra
  já embutida no desenho do executor; o motor de dry-run recebe dados prontos e não
  faz HTTP por construção).
- ETag/304: polling e reconciliação usam `If-None-Match` (primitivas da V1).
- KPI: recorte = 0 itens (tudo concluído antes de 2025-08). **Decisão recomendada:**
  migrar o board KPI integralmente mesmo assim (31 itens, dados de referência, custo
  ~zero) — aguarda seu OK; alternativa é mantê-lo só-leitura no Monday.

### F2.11 Dry-run — resultados reais

Ferramenta: `scripts/sunday_migration_dry_run.py` (relatório agregado sanitizado;
testes garantem que nenhum método de escrita é chamado). Recorte analisado: 4.391
itens → **2.060 no recorte** / 2.331 SKIP. Três cenários:

| Cenário | READY | MANUAL | ERROR | SKIP |
|---|---|---|---|---|
| Estado atual do Sunday | 0 (0%) | 2.060 (100%) | 0 | 2.331 |
| Pós-checklist (schema criado) | 491 (23,8%) | 1.569 (76,2%) | 0 | 2.331 |
| Pós-checklist + de-para de usuários aprovado | **2.060 (100%)** | **0** | **0** | 2.331 |

Motivos de MANUAL: estado atual — `MISSING_TARGET_COLUMN` 2.060 (todos; 6 boards nem
existem), `MISSING_USER_MAPPING` 1.569, `INVALID_RELATION_CONFIG` 57 (as colunas de
relação não existem/não apontam para o destino certo); pós-checklist —
`MISSING_USER_MAPPING` 1.569 (zera com o de-para aprovado). **Nenhum ERROR**: todas
as 57 conexões apontam para itens existentes nos boards de destino da Onda 1.
Flags informativas no recorte: 233 itens com arquivo (materialização), 1.104 com
updates, 104 com subitens (aditivos de Contratos — viram filhos nativos).

Esforço manual estimado: além do checklist (F2.12, ~2–4 h únicas de configuração) e
da aprovação do de-para de usuários (28 matches a revisar, ~30 min), **nenhum item
exige intervenção manual individual**. Fórmulas (2) e cronômetro (2) são configuração
única já incluída no checklist. Itens dos 30 usuários desativados migram sem
responsável (sem ação por item; registro no comentário de rastreio).

### F2.12 Checklist de configuração manual no Sunday (pré-Fase 3)

Ordem: primeiro os boards novos, depois colunas (as tabelas F2.3 dão nome/tipo
exatos de cada coluna; options de status = labels Monday 1:1), por último as
conexões (dependem dos IDs dos boards novos). Em todos os boards: criar também a
coluna **Monday ID** (Texto curto) — rastreabilidade.

- [ ] **Criar 6 boards** no workspace 22 (template board): `Legal - Procons`,
  `Legal - Prazos`, `Legal - Processos Judiciais`, `Legal - Processos Trabalhista`,
  `Legal - KPI Processos Consumidores` (se aprovado em F2.10), `Legal - Contratos`.
  Anotar o board_id de cada um (aparece na URL).
- [ ] **Legal - Contratos**: habilitar subitens (profundidade 2 — aditivos);
  criar as 10 colunas da tabela Contratos (F2.3), com options de Empresa e Vigência.
- [ ] **Legal - Processos Judiciais**: criar as ~33 colunas da tabela (12 status com
  options 1:1; fórmula "saving" recriada à mão; "Local da Audiência" como Texto).
- [ ] **Legal - Prazos**: criar colunas da tabela; coluna de conexão
  **"Processos Consumidores"** (Conectar board) apontando para o board **Legal -
  Processos Judiciais** recém-criado (source_board_id correto é obrigatório).
- [ ] **Board 72 (Legal - Audiências)**: criar as colunas restantes da tabela;
  **duas** colunas Conectar board "Processos Judiciais" (o Monday tem duas) → ambas
  apontando para Legal - Processos Judiciais.
- [ ] **Board 77 (Controle)**: criar grupos das filas (Jan / Luciano / Pendente
  Fornecedor / Assinados / Recusado); criar colunas da tabela (Status com as 5
  options; Quem Assina; Tipo com as 8 options; cronômetro se desejado); coluna
  Conectar board **"Contrato relacionado"** → Legal - Contratos.
- [ ] **Legal - Procons**: criar as ~20 colunas da tabela (10 status com options).
- [ ] **Legal - Processos Trabalhista / KPI**: criar colunas das tabelas (fórmula
  "Saved" à mão no Trabalhista).
- [ ] Conferir com o dry-run: `python scripts/sunday_migration_dry_run.py
  --refresh-sunday` (com o secret) — as relações devem sair `config_ok: true` e o
  cenário "estado_atual" deve convergir para o "pós-checklist".

Por quê: a API do Sunday não cria/altera colunas com token (F0.14/F0.15 — decisão
C, configuração manual aceitável); cada coluna acima é pré-requisito direto de uma
coluna Monday em uso real.

### F2.13 Ordem recomendada de migração (Fase 3)

1. **Legal - Contratos** — alvo das relações do Controle e pai dos 104 subitens.
2. **Legal - Processos Judiciais** — alvo das relações de Prazos e Audiências.
3. **Processos Trabalhista** e **KPI** (se aprovado) — pequenos, sem dependências.
4. **Prazos** — relações apontando para Processos (já migrado).
5. **Audiências** — idem (board 72).
6. **Procons** — independente; volume médio; arquivos com materialização.
7. **Controle Assinaturas** — por último: domínio mais crítico (sync Autentique
   ativo), relações para Contratos já migrado, e o cutover do polling acontece na
   fase seguinte.

Justificativa: boards-alvo de relação migram antes dos boards que apontam para eles
(o mapa de IDs precisa do destino resolvido); os críticos ficam por último para
maximizar aprendizado com os de menor risco.

### F2.14 Decisão para a Fase 3

**GO COM PRÉ-REQUISITOS.** Nenhum bloqueante técnico: 0 ERROR no dry-run, 100% READY
no cenário completo, relações íntegras, ferramentas e ledger desenhados. Pré-requisitos
(seus):

1. Executar o checklist F2.12 no Sunday (~2–4 h, única vez) e me passar os board_ids
   criados.
2. Aprovar o de-para de usuários: na Fase 3, com o secret disponível, eu gero a
   proposta MATCH_EXATO por e-mail (28 identidades) para sua aprovação; os 30
   desativados migram sem responsável (confirmar).
3. Decidir se o KPI entra integral (F2.10) e confirmar o recorte de Contratos
   ("Não Vigente" antigo fica no Monday, exceto os puxados por relação).
4. Garantir os secrets `SUNDAY_API_TOKEN`/`SUNDAY_API_URL` numa sessão nova para a
   execução (e, idealmente, o token da conta de serviço definitiva — decisão 2 da
   Fase 0).


---

## Fase 2.5 — Configuração manual assistida e preflight final (2026-08-11)

> Executada **100% em LEITURA** (GET no Sunday, GraphQL de leitura no Monday). Nenhum
> `POST`/`PATCH`/`DELETE` em Sunday ou Monday; nenhum item foi criado/alterado; nenhum
> dado migrado. Objetivo: validar os 8 boards da Onda 1 já criados no workspace 22,
> validar o schema atual, fazer o matching exato de usuários e gerar o **checklist
> manual completo** para configuração humana no app do Sunday antes da Fase 3.

### F2.5.1 IDs definitivos da Onda 1 (confirmados por leitura)

Os 6 boards novos foram criados manualmente no workspace 22; os 2 já existentes
permanecem conforme o mapping da Fase 2 (F2.2). Todos os 8 confirmados presentes em
`GET /workspaces/22` (`Support - Finance, Legal, People`):

| Board (nome no app) | Sunday board_id | Origem Monday | Nome confere? |
|---|---|---|---|
| Legal - Audiências | `72` | Audiências (4443295406) | ✅ exato |
| Legal - Controle de Assinaturas - Jan & Luciano | `77` | Controle Assinaturas (5301515799) | ⚠️ nome real tem sufixo "- Jan & Luciano" |
| Legal - Procons | `82` | Procons (4944254220) | ✅ exato |
| Legal - Prazos | `83` | Prazos (3961072966) | ✅ exato |
| Legal - Processos Judiciais | `84` | Processos Judiciais (5343921475) | ✅ exato |
| Legal - Processos Trabalhista | `85` | Processos Trabalhista (4443297481) | ✅ exato |
| Legal - KPI Processos Consumidores | `86` | KPI - Processos Consumidores (5563754463) | ✅ exato |
| Legal - Contratos | `87` | Contratos (5385471914) | ✅ exato |

**Discrepância de nome (board 77):** o nome real no Sunday é
`Legal - Controle de Assinaturas - Jan & Luciano` (idêntico ao registrado na F0.13 e no
mapping F2.2), não o encurtado `Legal - Controle de Assinaturas`. O ID `77` é
inequívoco e corresponde ao board de Controle. Conforme instrução "não renomear nada",
**nada foi alterado**; fica para decisão humana manter o nome atual (recomendado — bate
com F2.2) ou encurtar no app.

### F2.5.2 Schema atual dos 8 boards (leitura)

Estado idêntico em todos: cada board tem **apenas as 5 colunas de sistema do template**
e o `status_set` de sistema `to_do`/`follow_up`/`done`. **Nenhuma coluna customizada da
F2.3 existe ainda** — confirma o cenário "estado atual" do dry-run
(`MISSING_TARGET_COLUMN` em 100%).

Colunas de sistema (não recriar) por board — `label` (`key`, tipo):
`Nome` (`name`, text) · `Status` (`status`, status de sistema) ·
`Responsável` (`owner`, people) · `Data` (`target_date`, date) ·
`Área` (`area`, dropdown, `options=[]`).

| Board | Grupos atuais |
|---|---|
| 72 Audiências | `Itens` (218), `Audiencias Pendentes` (219) |
| 77 Controle | `Itens` (227) |
| 82 Procons | `Itens` (251) |
| 83 Prazos | `Itens` (252) |
| 84 Processos Judiciais | `Itens` (253) |
| 85 Processos Trabalhista | `Itens` (254) |
| 86 KPI | `Itens` (255) |
| 87 Contratos | `Itens` (256) |

`capabilities` em todos: `process=false`, `subitems=false`, `approvals=false`,
`time_tracking=false`, `calendar_anchor=true`; `hierarchy_depth=1`. Importante para o
board 87 (subitens dos aditivos — ver F2.5.7).

### F2.5.3 Secrets — nota de configuração

Os dois secrets existem na sessão, mas estão **trocados/malformados**:
`SUNDAY_API_URL` contém o **token** (`sun_pat_…`) e `SUNDAY_API_TOKEN` contém um
**snippet `curl`** com a URL embutida. A validação desta fase reconstruiu os valores
corretos em memória (base `https://sunday-api-…run.app`, token `sun_pat_…`) apenas para
as leituras. **Antes da Fase 3 / do `--refresh-sunday`, corrigir os secrets**:
`SUNDAY_API_URL=https://sunday-api-…run.app` e `SUNDAY_API_TOKEN=sun_pat_…`. Nenhum
valor de secret foi impresso.

### F2.5.4 Matching de usuários (leitura de `GET /users/directory`)

Comparação **e-mail exato** (sha256(email)[:16], sem fuzzy) contra as 28 identidades
técnicas ativas do Monday (`docs/monday-user-identities-2026-08-11.json`):

- **MATCH EXATO: 25**
- **SEM MATCH: 3** (ativos no Monday sem e-mail correspondente no diretório Sunday)
- **30 desativados/sem identidade suficiente:** decisão definitiva **MIGRAR SEM
  RESPONSÁVEL** (não atribuir pessoa semelhante).

Diretório Sunday: 80 usuários (todos com e-mail). Nenhum e-mail foi exibido. O
`sunday_user_id` de cada match será resolvido/aplicado só na Fase 3.

### F2.5.5 Checklist manual — colunas por board

Regras gerais para todos os boards:

- **A) Colunas de sistema que NÃO recriar:** `Nome`, `Status` (sistema), `Responsável`,
  `Data` (sistema), `Área`.
- **C) Coluna técnica obrigatória em TODOS:** **`Monday ID`** (Texto) —
  rastreabilidade/idempotência (F2.9).
- **D) Substituições:** colunas `file` do Monday → **anexo por link** no item (não vira
  coluna); `location` → coluna **Texto**; `time_tracking` → coluna **Número**
  ("… (horas)"); `formula` → coluna **Fórmula** (F2.5.6).
- **People:** o responsável principal usa a coluna de sistema **`Responsável`** (não
  criar). Onde o Monday tem uma **segunda** coluna de pessoas (só em Processos
  Judiciais), criar uma coluna **Pessoas** customizada para não perder o dado.
- **Datas:** como há várias datas por board e o sistema só tem uma (`Data`), criar as
  datas como colunas **Data** customizadas (a `Data` de sistema pode ficar sem uso).
- **Status de negócio:** SEMPRE coluna **Status** customizada com options 1:1 (F2.5.6);
  **não** usar o status de sistema como substituto (ele é derivado — F2.4).

Contagem de colunas customizadas a criar (fora as 5 de sistema; `file`→anexo não conta):
Procons ~20 · Prazos ~8 · Audiências ~13 · Processos Judiciais ~33 · Trabalhista ~14 ·
KPI ~15 · Controle ~13 · Contratos ~9 — todas com "Monday ID" incluída.

### F2.5.6 De-para de STATUS (Label → Key) — exato, sem fuzzy

Keys geradas pelo slug determinístico da Fase 2 (`slugify_status_key`). Criar cada
coluna como tipo **Status** e cadastrar as options exatamente com estes labels; as keys
são o identificador estável usado pela migração.

**82 Procons**
- `Origem`: Men's "Loja"→`men_s_loja` · Glam "Clube"→`glam_clube` · Glam "Loja"→`glam_loja` · Men's "Clube"→`men_s_clube`
- `Houve Cancelamento de Assinatura?`: Não→`nao` · Sim→`sim`
- `Status`: Baixado→`baixado` · Respondido→`respondido`
- `Causa 1`: Problemas com Cancelamento→`problemas_com_cancelamento` · Renovação Automática→`renovacao_automatica` · Problemas na experiência→`problemas_na_experiencia` · Problemas no pagamento→`problemas_no_pagamento` · Problemas com entrega→`problemas_com_entrega`
- `Causa 2 (se houver)`: Problemas com Cancelamento→`problemas_com_cancelamento` · Problemas com Entrega→`problemas_com_entrega` · Problemas com Pagamentos→`problemas_com_pagamentos` · Renovação Automática→`renovacao_automatica` · Problemas na Experiência→`problemas_na_experiencia`
- `Causa 3 (se houver)`: Problemas com Cancelamento→`problemas_com_cancelamento` · Problemas com Entrega→`problemas_com_entrega` · Renovação Automática→`renovacao_automatica` · Problemas com Pagamento→`problemas_com_pagamento` · Problemas na Experiência→`problemas_na_experiencia`
- `Causa 4 (se houver)`: Problemas com Cancelamento→`problemas_com_cancelamento` · Problemas com a Experiência→`problemas_com_a_experiencia` · Problemas com a Entrega→`problemas_com_a_entrega` · Renovação Automática→`renovacao_automatica` · Problemas no pagamento→`problemas_no_pagamento`
- `Gerou Processo Administrativo`: Sim→`sim` · Não→`nao`
- `Processo Administrativo Respondido`: Sim→`sim` · Não→`nao` · Cancelado→`cancelado`
- `Já está na black list?`: Não→`nao` · Sim→`sim` · Em análise→`em_analise`

**83 Prazos**
- `Processo Administrativo`: Não→`nao` · Sim→`sim`
- `Status`: Em progresso→`em_progresso` · Feito→`feito` · Parado→`parado` · Não realizada→`nao_realizada` · Não Iniciado→`nao_iniciado` · Cancelada→`cancelada`

**72 Audiências**
- `Presencial ou Virtual`: Presencial→`presencial` · Virtual→`virtual`
- `Responsável por comparecer`: Metajur→`metajur` · Interno-B4A→`interno_b4a` · LBZ→`lbz`
- `Status documentos`: Prontos - pendente Protocolo→`prontos_pendente_protocolo` · Já Apresentados→`ja_apresentados` · A Fazer→`a_fazer`
- `Processo/Procon`: Procon→`procon` · Processo→`processo` · Outro→`outro`
- `Status`: Aguardando→`aguardando` · Feito→`feito` · Cancelada→`cancelada` · Em Andamento→`em_andamento` · Encerrado→`encerrado`

**84 Processos Judiciais**
- `Processo relacionado a`: Tributário→`tributario` · Consumidor→`consumidor` · Criminal→`criminal` · Administrativo→`administrativo` · Cível→`civel` · Trabalhista→`trabalhista`
- `Sistema`: ESAJ→`esaj` · PJE→`pje` · PROJUDI→`projudi` · SISTEMA PRÓPRIO→`sistema_proprio` · EPROC→`eproc`
- `Órgão/JEC`: JEC→`jec` · VC→`vc` · TRF→`trf` · VF→`vf` · JT→`jt`
- `TJ`: TJAC→`tjac` · TJSP→`tjsp` · TJAL→`tjal` · TJAM→`tjam` · TJDF→`tjdf` · TJBA→`tjba` · TJES→`tjes` · TJCE→`tjce` · TJGO→`tjgo` · TJMA→`tjma` · TJAP→`tjap` · TJMG→`tjmg` · TJMS→`tjms` · TJMT→`tjmt` · TJPA→`tjpa` · TJPB→`tjpb` · TJPE→`tjpe` · TJPI→`tjpi` · TJPR→`tjpr` · TJRJ→`tjrj` · TJRN→`tjrn` · TJRO→`tjro` · TJRR→`tjrr` · TJRS→`tjrs` · TJSC→`tjsc` · TJSE→`tjse` · TJTO→`tjto` · TRT2→`trt2`
- `Houve Cancelamento de Assinatura?`: Não→`nao` · Sim→`sim`
- `Audiência`: Sim→`sim` · Não→`nao`
- `Risco`: Possível→`possivel` · Remoto→`remoto` · Provável→`provavel`
- `Problema Principal (se aplicável)`: Renovação Automática→`renovacao_automatica` · Problemas na Entrega→`problemas_na_entrega` · Problemas com Cancelamento→`problemas_com_cancelamento` · Problemas no Pagamento→`problemas_no_pagamento` · Problemas na Experiência→`problemas_na_experiencia`
- `Status`: Encerrado→`encerrado` · Em Andamento→`em_andamento` · Suspenso→`suspenso`
- `Decisão Judicial`: Acordo→`acordo` · Improcedente Favoravel a B4A/MMKT→`improcedente_favoravel_a_b4a_mmkt` · Condenação B4A/MMKT→`condenacao_b4a_mmkt` · Procedente Favoravel B4A/MMKT→`procedente_favoravel_b4a_mmkt` · Improcedente Desfavoravel B4A/MMKT→`improcedente_desfavoravel_b4a_mmkt`

**85 Processos Trabalhista**
- `Status`: Em andamento→`em_andamento` · Encerrado→`encerrado`
- `Tipo de Processo`: Judicial - Tributária→`judicial_tributaria` · Judicial - Trabalhista→`judicial_trabalhista` · Judicial - Cível→`judicial_civel` · Administrativo→`administrativo` · Criminal→`criminal` · Judicial - Consumidor→`judicial_consumidor` · Administrativo - Regulatório→`administrativo_regulatorio`
- `Risco`: Possível→`possivel` · Remoto→`remoto` · Provável→`provavel`
- `Forma de Contratação`: Terceirizado→`terceirizado` · CLT→`clt` · PJ→`pj` · Estagiário→`estagiario` · N/A→`n_a`

**86 KPI Processos Consumidores**
- `Estado`: 27 UFs — AL→`al` · ES→`es` · RJ→`rj` · AC→`ac` · AP→`ap` · SP→`sp` · AM→`am` · MG→`mg` · PI→`pi` · BA→`ba` · DF→`df` · MT→`mt` · RS→`rs` · MS→`ms` · SC→`sc` · GO→`go` · TO→`to` · SE→`se` · CE→`ce` · MA→`ma` · PA→`pa` · PR→`pr` · PB→`pb` · PE→`pe` · RN→`rn` · RO→`ro` · RR→`rr`
- `Ré`: B4A & MMKT→`b4a_mmkt` · B4A→`b4a` · MMKT→`mmkt`
- `Causa 1`: Renovação Automática→`renovacao_automatica` · Problemas na Experiência→`problemas_na_experiencia` · Problemas no pagamento→`problemas_no_pagamento` · Problemas com Entrega→`problemas_com_entrega` · Problemas com Cancelamento→`problemas_com_cancelamento`
- `Causa 2`: Renovação Automática→`renovacao_automatica` · Problemas com o Pagamento→`problemas_com_o_pagamento` · Problemas com a Experiência→`problemas_com_a_experiencia` · Problemas com o Cancelamento→`problemas_com_o_cancelamento` · Problemas na Entrega→`problemas_na_entrega`
- `Causa 3`: Renovação Automática→`renovacao_automatica` · Problemas com o Pagamento→`problemas_com_o_pagamento` · Problemas na Experiência→`problemas_na_experiencia` · Problemas no Cancelamento→`problemas_no_cancelamento` · Problemas na Entrega→`problemas_na_entrega`
- `Situação`: Arquivado→`arquivado` · Ativo→`ativo`
- `Resultado`: Em andamento→`em_andamento` · Improcedência→`improcedencia` · Condenação→`condenacao` · Em Recurso (Nosso)→`em_recurso_nosso` · Acordo→`acordo`

**77 Controle de Assinaturas**
- `Status`: Aguardando Assinatura→`aguardando_assinatura` · Assinado→`assinado` · Recusado→`recusado` · Aguardando outros→`aguardando_outros` · Bloqueado - aguardando providencia→`bloqueado_aguardando_providencia`
- `Priority`: Urgente ⚠️→`urgente` · Normal→`normal`
- `Quem Assina`: Luciano→`luciano` · Jan→`jan`
- `Tipo`: Contratos MMKT→`contratos_mmkt` · Contratos B4A→`contratos_b4a` · Contratos Itaro→`contratos_itaro` · Contratos RV BVI→`contratos_rv_bvi` · Contratos B2B→`contratos_b2b` · NDA→`nda` · Contratos Societários→`contratos_societarios` · Contratos Influencers (Queens)→`contratos_influencers_queens` · Contratos Jan→`contratos_jan` · Contratos Aurora→`contratos_aurora` · Pedidos Marcas Próprias→`pedidos_marcas_proprias` · RH→`rh`

**87 Contratos**
- `Empresa`: B4A & MMKT→`b4a_mmkt` · Itaro→`itaro` · B4A→`b4a` · MMKT→`mmkt` · Aurora→`aurora` · RV BVI→`rv_bvi` · Jan→`jan`
- `Vigência`: Vigente→`vigente` · Não Vigente→`nao_vigente`

### F2.5.7 Board 87 (Contratos) — subitens dos 104 aditivos

Pela API, **não é possível confirmar** suporte a subitens: `capabilities.subitems=false`
e `hierarchy_depth=1` no board 87; o token não altera essa configuração
(`PATCH /boards/{id}` → 403). Nota: na F0.14, a criação de subitem via `parent_item_id`
funcionou no sandbox mesmo com o flag desligado — porém, para garantir a exibição
hierárquica no app, **ativar manualmente**:

1. Abra o board **Legal - Contratos** (87).
2. Canto superior direito do board → menu **⋯ / Configurações do board**.
3. Procure **Subitens / Hierarquia** (ou "Habilitar subitens") e **ative** (profundidade
   2). Se aparecer o botão de adicionar subitem numa linha (seta/`+` de expandir item),
   já está ativo.
4. **Não crie subitens reais agora.**

### F2.5.8 Colunas/config específicas de Contratos (F2.3/F2.12)

Board 87 — criar (além de `Monday ID`):
- `Empresa` — Status (options acima) · `CNPJ outra Parte` — Texto ·
  `Tipo de Contrato` — Texto · `Data do Contrato` — Data · `Término` — Data ·
  `Vigência` — Status (options acima) · `Observações` — Texto longo.
- `Contrato` (arquivo Monday) → **anexo por link** (não vira coluna).
- `Responsável` (people) → coluna de sistema **Responsável**.
- Subitens (aditivos) → **subitens nativos** (F2.5.7); não é coluna.
- Grupos por Tipo do Monday (RH, Contratos B4A, … 17 grupos) **não** são pré-requisito
  da migração — a categorização vive na coluna `Empresa`/`Vigência` e no fluxo de
  contratos; não criar por ora.

### F2.5.9 Board 77 (Controle) — grupos a criar

Nomes **exatos** do Monday (board 5301515799). Board 77 hoje só tem `Itens`; criar:

- `Contratos Pendentes de Assinatura Jan`
- `Contratos Pendentes de Assinatura Luciano`
- `Pendente Fornecedor`
- `Assinados`
- `Recusado`

Criar já com o nome exato (renomear grupo é bloqueado para o token — F0.14).

### F2.5.10 Área

`Área` é coluna estrutural de sistema (dropdown, `is_system=true`, `options=[]`) — não
excluir, não recriar, não renomear.

| Board | Decisão |
|---|---|
| 72 Audiências | Área: IGNORAR |
| 77 Controle | Área: IGNORAR |
| 82 Procons | Área: IGNORAR |
| 83 Prazos | Área: IGNORAR |
| 84 Processos Judiciais | Área: IGNORAR |
| 85 Processos Trabalhista | Área: IGNORAR |
| 86 KPI | Área: IGNORAR |
| 87 Contratos | Área: IGNORAR |

Fase 2 (F2.3) deixou uma preferência **opcional** (não decidida) de preencher Área com
valor fixo em Procons ("Consumidor") e Contratos/Controle ("Contratos") apenas se o time
quiser usar os filtros da home — como não foi definido, aqui fica **IGNORAR**.

### F2.5.11 Fórmulas (configuração manual)

Duas colunas `formula` (não há transpiler; recriar à mão **depois** das colunas de
número de que dependem):

| Board | Nome | Origem Monday | Equivalente Sunday | Dependências |
|---|---|---|---|---|
| 84 Processos Judiciais | `saving` | `{valor da causa} - {condenação}` | Fórmula: `{valor da causa} - {condenação}` | criar antes: `valor da causa`, `condenação` (Número) |
| 85 Processos Trabalhista | `Saved` | `{Valor da Causa} - {Depósito/Pagamento} - {Provisão}` | Fórmula: `{Valor da Causa} - {Depósito/Pagamento} - {Provisão}` | criar antes: `Valor da Causa`, `Depósito/Pagamento`, `Provisão` (Número) |

A linguagem de expressão do Sunday pode diferir na sintaxe de referência de coluna;
se não houver equivalente literal, deixar a coluna Número e calcular no relatório.

### F2.5.12 Relações entre boards (board_relation) — config exata

IDs de destino agora conhecidos. Criar cada coluna **Conectar board** com o
`source_board_id` exato **antes** da migração (o dry-run pós-checklist confere
`config_ok`). A API Sunday **não** valida o board-alvo — `source_board_id` errado deve
bloquear o dry-run.

| # | Origem (board) | ID origem | Coluna (nome exato) | Tipo | Destino | ID destino / `source_board_id` | Cardinalidade |
|---|---|---|---|---|---|---|---|
| 1 | Legal - Prazos | `83` | `Processos Consumidores` | Conectar board | Legal - Processos Judiciais | `84` | muitos→1 (lista suportada) |
| 2 | Legal - Audiências | `72` | `Processos Judiciais` | Conectar board | Legal - Processos Judiciais | `84` | muitos→1 |
| 3 | Legal - Audiências | `72` | `Processos Judiciais (2)` | Conectar board | Legal - Processos Judiciais | `84` | muitos→1 |
| 4 | Legal - Controle | `77` | `Contrato relacionado` | Conectar board | Legal - Contratos | `87` | muitos→1 |

Observação (2): o Monday tem **duas** colunas homônimas "Processos Judiciais" em
Audiências (`conectar_quadros__1`, `conectar_quadros8__1`) — criar as duas no Sunday
(sugerido diferenciar a segunda como `Processos Judiciais (2)`), ambas com
`source_board_id=84`.

**Quarta relação identificada no inventário (F2.6):** a coluna do Controle
`link to Notificações Carol - Assinaturas Jan` (`board_relation_mkqxj7gv`) aponta para
um board **fora da Onda 1** → **NÃO MIGRAR** (registrada em comentário; não criar coluna
de relação para ela).

### F2.5.13 Ordem recomendada de execução manual

1. Confirmar/ativar **subitens no board 87** (F2.5.7).
2. Criar **colunas Número** dependentes das fórmulas em 84 e 85 (F2.5.11).
3. Criar as demais colunas (Status/Texto/Texto longo/Data/Número/Link/E-mail) de cada
   board, com options 1:1 (F2.5.6), incluindo `Monday ID` em todos.
4. Criar as **fórmulas** `saving` (84) e `Saved` (85) depois dos números.
5. Criar os **grupos do board 77** (F2.5.9).
6. Criar as **colunas de relação** (F2.5.12) por último — dependem dos IDs de destino.
7. Corrigir os **secrets** (F2.5.3) e rodar
   `python scripts/sunday_migration_dry_run.py --refresh-sunday` — as relações devem
   sair `config_ok: true` e o cenário "estado_atual" convergir para "pós-checklist".

### F2.5.14 Decisões definitivas reafirmadas

- **KPI (86):** migra os **31 itens integralmente** (não aplicar o recorte normal).
- **30 usuários desativados:** migram **sem responsável** (não atribuir semelhante).
- **Nesta fase nada foi escrito** em Sunday/Monday. Próximo passo é humano: executar
  este checklist no app do Sunday; depois faremos leitura + `--refresh-sunday` + dry-run
  final antes da Fase 3.

---

## Escopo definitivo da migração — DECISÃO DO USUÁRIO (2026-08-12)

> O Monday será descontinuado. **Escopo final: TODOS os 4.391 itens dos 8 boards da
> Onda 1** — nenhum item permanece exclusivamente no Monday ao término do projeto.
> Esta seção substitui qualquer leitura anterior do recorte como "escopo"; o recorte
> passa a ser somente o plano de cutover. Origem: decisão explícita do usuário
> (registrada nesta data), encerrando a divergência entre cenários levantada na
> reconciliação de escopo.

### Duas ondas

- **Onda 1 — cutover operacional** (referência atual: **2.091 itens**): abertos/não
  concluídos + últimos 12 meses + pull-ins de relação + KPI integral (31). Codificado
  em `migration/mappings.py` (`WAVE1_FULL_BOARDS`) e `migration/dry_run.py`.
- **Onda 2 — backfill histórico** (referência atual: **2.300 itens**): todos os
  demais, obrigatórios. Meta final: **4.391/4.391** no Sunday.
- Contratos: 1.119 no total (963 na Onda 1); Controle: 1.607 no total (553 na
  Onda 1) — **Controle NÃO é greenfield**.

### Regra fundamental (sem descarte, sem invenção)

Nenhum item histórico é descartado por data anterior ao cutoff, conclusão, ausência
de data/vigência/responsável ou grupo histórico. **Dados ausentes permanecem
ausentes** — a migração nunca inventa valores (Data do Contrato/Término vazios
migram vazios; Vigência sem base não é inferida; grupo Monday alimenta Tipo conforme
o mapping aprovado; "Contratos Encerrados" → Vigência = Não Vigente pela regra
validada).

### Classificação do dry-run (implementada)

`WAVE_1_READY` · `WAVE_2_HISTORICAL` (reason `HISTORICAL_BACKFILL`; `wave="onda2"`;
contabilizado como obrigatório para a Onda 2) · `MANUAL` · `ERROR`. O relatório
agregado passa a reportar `onda1_total`, `onda2_backfill_obrigatorio` e
`meta_final`. Números reais (inventário de 2026-08-11):

| Cenário | WAVE_1_READY | MANUAL | ERROR | WAVE_2_HISTORICAL |
|---|---|---|---|---|
| Estado atual | 0 | 2.091 (checklist pendente) | 0 | 2.300 |
| Pós-checklist + de-para aprovado | **2.091 (100% da Onda 1)** | 0 | 0 | 2.300 (Onda 2) |

### Arquitetura de duas ondas sem duplicação (validada)

1. **Idempotência**: ledger `data/monday-sunday-map.json` indexado por
   `monday_board_id:monday_item_id` + coluna **Monday ID** em cada item migrado — o
   executor consulta o ledger (O(1)) antes de criar; reexecução e Onda 2 nunca
   duplicam; o mapa é reconstruível lendo o Sunday.
2. **Relações entre ondas**: (a) fonte na Onda 1 → alvo sempre presente na Onda 1
   (pull-in garante); (b) fonte na Onda 2 → alvo da Onda 1 resolvido pelo ledger
   (`sunday_item_id` já existente); (c) fonte e alvo na Onda 2 → mesma ordem por
   board da Onda 1 (alvos antes das origens). Relações são gravadas em **segunda
   passada**, depois que os dois lados existem.
3. **Arquivos/updates históricos**: o mesmo executor da Onda 1 roda na Onda 2 (item
   + values + comments + anexos por item); nada no client/dry-run é específico de
   onda.

### Alterações de código desta decisão

`migration/models.py` (novas classificações + campo `wave` + reason
`HISTORICAL_BACKFILL`), `migration/mappings.py` (`WAVE1_FULL_BOARDS` com o KPI),
`migration/dry_run.py` (seleção da Onda 1 com boards integrais; itens fora viram
`WAVE_2_HISTORICAL`; payload com totais por onda), `scripts/sunday_migration_dry_run.py`
(saída por onda) e testes (33 no módulo, incluindo conservação do total —
`sum(counts) == total analisado`). Nenhuma migração executada; Monday e Sunday
intocados.

---

## Fase 3 — Infraestrutura do executor (2026-08-12; sem nenhuma escrita)

> Implementação autorizada; APPLY **não** executado. O executor consome
> exclusivamente a engine canônica (`migration.dry_run` + disposições) — sem
> segunda engine. Zero POST/PATCH/DELETE contra o Sunday nesta fase.

- `migration/executor.py`: modos **PLAN (default)** e **APPLY fail-closed**
  (exige `mode=apply` + `confirm_writes` + `SUNDAY_MIGRATION_ALLOW_APPLY=1` +
  gate 100% OK + snapshot revalidado; aborta antes da 1ª escrita). Allowlist
  fixa dos 8 boards; `--max-items` aborta plano maior; dispositions
  CREATE/ADOPT/ABSORB/EXCLUDE_TEST respeitadas sem fallback para CREATE;
  idempotência dupla (ledger `monday:item` + índice Monday ID no Sunday);
  ledger persistido só após operação confirmada (atômico), nunca no PLAN;
  relações em 2ª passada global resolvidas via ledger (unresolved bloqueia
  APPLY); secrets somente pelos aliases `SUNDAY_API_URL_TEST`/`SUNDAY_API_TOKEN_TEST`
  (sem fallback; sem impressão); marcadores de idempotência para comments
  (`[monday-migracao:item:update]`) e anexos (`monday-asset-<id>`).
- CLI: `scripts/sunday_migration_execute.py --board … --wave … --mode plan
  --max-items … [--refresh-sunday]`.
- Testes: `tests/test_sunday_migration_executor.py` (23 casos: plan-never-writes,
  flags do APPLY, allowlist, max-items, snapshot guard, dispositions, many→one,
  usuários 25/3/30 + novo bloqueia, idempotências, falha parcial + reexecução
  sem duplicar, relações 2ª passada, subitens 87, schema checks, vazamento de
  secrets). Suíte completa: 1133 passed / 1 skipped; ruff limpo.
- **PLAN real do KPI (Monday 5563754463 → Sunday 86, WAVE_1)**: snapshot live
  fingerprint `a4de634dbe6b545ade7a0442`, **31 source rows = 31 CREATE**, 0
  bloqueados, 0 comments, 0 anexos, 0 relações; gate 5/6 OK — reprova apenas
  `schema_live_verificado` (secrets `*_TEST` ausentes nesta VM; fail-closed
  funcionando). Pré-requisitos do piloto: secrets `*_TEST` numa sessão nova,
  coluna **Monday ID** no board 86 e re-PLAN com `--refresh-sunday`.
