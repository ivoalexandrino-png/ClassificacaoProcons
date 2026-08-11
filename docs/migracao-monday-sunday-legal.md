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

---

## Resultado da Fase 0 - Sunday API

### Validação autenticada de leitura (2026-08-10)

Esta validação usou exclusivamente requisições `GET` autenticadas com o token injetado na
VM. Não houve criação, alteração, upload ou exclusão de qualquer recurso no Sunday ou no
Monday.

**Autenticação e identidade**

- O token foi aceito pelo Sunday: `GET /health`, `GET /auth/me`,
  `GET /workspaces/mine`, `GET /workspaces/22` e `GET /boards` retornaram `200`.
- Há endpoint de identidade (`GET /auth/me`). O token está associado a um usuário Sunday
  habilitado, com `access_level` **`contributor`**, sem `admin_scopes`.
- No workspace 22, esse usuário tem papel **`member`**. Portanto, o token não tem privilégio
  administrativo nem leitura detalhada de boards.

**Workspace e boards confirmados**

- O workspace de destino existe e usa ID textual **`"22"`**: `Support - Finance, Legal,
  People`.
- A resposta informa `board_count: 6` e retorna os seis boards abaixo. Todos os IDs de
  workspace e board observados são strings, não inteiros.

| Sunday ID | Board |
|---|---|
| `"57"` | Weekly Support |
| `"59"` | Legal - Audiências |
| `"63"` | Cronograma + Processos Finance |
| `"66"` | Legal - Controle de Assinaturas - Jan & Luciano |
| `"67"` | Legal - Acessos |
| `"68"` | Legal - Seguros |

**Correção importante das hipóteses da descoberta não autenticada**

- A API REST, o header `X-Sunday-Token` e os endpoints de listagem de workspace/boards foram
  confirmados com autenticação real.
- A hipótese de que o token permitiria levantar o shape completo dos boards foi corrigida:
  para todos os seis boards, o token retorna **`403 Forbidden`** em `GET /boards/{id}`,
  `GET /boards/{id}/groups`, `GET /boards/{id}/columns`, `GET /boards/{id}/items` e
  `GET /boards/{id}/automations`.
- Consequentemente, os endpoints de `values`, comentários e anexos não puderam ser
  alcançados por item nesta credencial. Não é possível confirmar grupos, colunas, tipos de
  coluna, itens, values, comentários, anexos, automações, nem o formato dos IDs desses
  recursos sem acesso de leitura a pelo menos um board.
- Não foram observados headers de paginação ou de rate limit nas respostas `200` e `403`.
  O endpoint `GET /boards` retornou uma lista plana com seis elementos; isso não confirma a
  inexistência de paginação ou limites em endpoints autorizados.

**Pendências para concluir a parte somente leitura**

1. Usar um token que tenha acesso de leitura a um board do workspace 22, ou conceder ao token
   atual permissão de visualização em um board sandbox. Então repetir as leituras de grupos,
   colunas, itens, values, comentários, anexos e automações.
2. Com essa leitura autorizada, confirmar os tipos e formatos reais de IDs de grupo, coluna,
   item, value, comentário e anexo, além de paginação e rate limit eventualmente expostos
   nesses endpoints.

**Pendências que exigem teste de escrita autorizado em sandbox**

1. Criar uma automação `webhook` e gerar um evento para confirmar método HTTP, headers,
   payload, retries e timeout.
2. Criar colunas e gravar values válidos e inválidos para confirmar validação e coerção por
   tipo.
3. Fazer upload de um anexo pequeno para confirmar limite, resposta e associação ao item.
4. Criar uma relação entre boards para verificar a restrição entre workspaces.
5. Criar uma coluna `time_tracking` para confirmar se esse tipo é aceito pela API.

---

## Fase 0 — Reteste de *values* e `board_relation` (2026-08-11)

> Reteste **focado**, executado no sandbox autorizado (workspace 22, boards **80**
> `SANDBOX - API SUNDAY - NÃO USAR` e **81** `SANDBOX - API SUNDAY - RELATION`), com dados
> 100% fictícios. Nada foi tocado no Monday e nenhum outro board sofreu escrita. O token e a
> identidade do usuário não foram impressos nem gravados. Script reproduzível:
> `scripts/sunday_fase0_values_retest.py`; passo a passo sanitizado (37 chamadas):
> `docs/sunday-fase0-values-report-2026-08-11.json`.

**Decisão de arquitetura assumida (do pedido):** o *schema* dos boards é configurado
**manualmente** no Sunday; o adapter só manipula **dados**. Portanto o 403 na criação de
colunas (confirmado na F0.14) é **`C — configuração manual aceitável`**, não bloqueante.

### Duas rotas de escrita (descoberta central)

O board 80 já vem com **colunas de sistema** (`is_system: true`, embutidas em todo board:
`name`, `status`, `owner`, `target_date`, `area`) além das colunas custom. As duas famílias
gravam por rotas diferentes — o adapter precisa decidir a rota **por coluna**, lendo
`is_system`/`key` de `GET /boards/{id}/columns`:

- **Colunas de sistema** → `PATCH /boards/items/{id}` (campos `name`, `target_date`,
  `owner_user_id`, `area`…) e `PATCH /boards/items/{id}/status`. O endpoint de values as
  **recusa** com `400 "System columns são atualizadas via PATCH /boards/items/:id."`.
- **Colunas custom** → `PATCH /boards/items/{id}/values/{columnId}` com corpo `{"value": …}`.
- **Leitura de ambas**: values custom via `GET /boards/items/{id}/values`
  (`[{column_id, value, …}]`); campos de sistema no próprio objeto do item
  (`GET /boards/{id}/items`).

> ⚠️ No sandbox, o operador rotulou as colunas de sistema como se fossem custom
> (`TESTE - Texto` = `name`; `TESTE - Status` = `status`; `TESTE - Data` = `target_date`;
> `TESTE - Responsável` = `owner`). Por isso Texto/Status/Data/People foram validados pela
> rota de sistema. Número/Link/Checkbox/Relação são custom de verdade e validaram a rota de
> values — cobrindo **as duas rotas**.

### 1. Column IDs encontrados (board 80)

| Coluna (rótulo) | column_id | key | type | is_system | Rota de escrita |
|---|---|---|---|---|---|
| TESTE - Texto | `443` | `name` | text | **sim** | `PATCH /boards/items/{id}` (name) |
| TESTE - Número | `453` | `teste_numero` | number | não | `PATCH …/values/453` |
| TESTE - Status | `444` | `status` | status | **sim** | `PATCH …/items/{id}/status` |
| TESTE - Data | `446` | `target_date` | date | **sim** | `PATCH /boards/items/{id}` (target_date) |
| TESTE - Responsável | `445` | `owner` | people | **sim** | `PATCH /boards/items/{id}` (owner_user_id) |
| TESTE - Link | `454` | `teste_link` | link | não | `PATCH …/values/454` |
| TESTE - Checkbox | `455` | `teste_checkbox` | checkbox | não | `PATCH …/values/455` |
| TESTE - Relação | `456` | `teste_relacao` | board_relation | não | `PATCH …/values/456` |

Status de sistema disponível (`board.status_set`): `to_do` (A fazer), `follow_up`
(Follow-up), `done` (Feito).

### 2–9. Resultado por tipo (round-trip gravar→ler)

| # | Tipo | Payload enviado (aceito) | GET devolve | Round-trip |
|---|---|---|---|---|
| 3 | Texto (`name`) | `PATCH item {"name":"Teste Sunday API"}` | `name:"Teste Sunday API"` | ✅ igual |
| 4 | Número | `PATCH values {"value":12345}` | `12345` (int) | ✅ igual |
| 5 | Status | `PATCH …/status {"status":"follow_up"}` | `status:"follow_up"` | ✅ igual |
| 6 | Data | `PATCH item {"target_date":"2026-01-15"}` | `"2026-01-15T12:00:00.000Z"` | ✅ (grava `YYYY-MM-DD`, lê ISO datetime, 12:00Z) |
| 7 | Checkbox | `PATCH values {"value":true}` / `false` | `true` / `false` (bool) | ✅ ambos |
| 8 | Link | `PATCH values {"value":"https://example.com/teste-sunday-api"}` | string idêntica | ✅ igual |
| 9 | People | `PATCH item {"owner_user_id":<me>}` (id via `GET /auth/me`) | `owner_user_id` = enviado | ✅ igual |

- **People não é bloqueante** e, além disso, **funciona**: a rota de values recusa (`400`,
  system column), mas `owner_user_id` no `PATCH` do item grava e relê corretamente. Não foi
  inventado `user_id`: usou-se o próprio usuário autenticado (`GET /auth/me`).

### 10. `board_relation` — o teste mais importante

A coluna `TESTE - RELAÇÃO` (456) veio configurada com `settings.source_board_id = "79"`
(**board `79` = "Legal - Seguros"**, e **não** o board 81, como o enunciado presumia — ver
"ressalva de configuração" abaixo). Testes (todos gravando **apenas** no item do board 80;
board 79 só foi **lido**):

- Alvo em **board 81** (item fictício `TESTE TARGET RELATION - PODE EXCLUIR`, criado aqui):
  **aceito** (`200`) — a API **não valida** se o alvo pertence ao board conectado.
- Alvo em **board 79** (item fictício preexistente `PODE EXCLUIR`, apenas referenciado):
  **aceito** (`200`).
- Ambos os formatos de `value` são aceitos e persistidos **como enviados**:
  - `{"links":[{"item_id":"<id>"}]}` → GET devolve `{"links":[{"item_id":"<id>"}]}`
    (**formato robusto: suporta múltiplos alvos** — ex.: Controle tem 2 `board_relation`);
  - `"<id>"` (string simples) → GET devolve `"<id>"` (atalho de alvo único).
- **Sem escrita recíproca**: os values do item-alvo (7655) eram `[]` antes e continuaram
  `[]` depois — gravar a relação **não** cria back-reference no board conectado (só muta o
  item de origem, o que também confirma o guard-rail de não escrever em outros boards).

**Respostas objetivas (Teste 10):**

1. **O Sunday aceitou gravar a relação?** Sim (`200`), nos dois formatos.
2. **O GET dos values devolve o target item_id?** Sim — em
   `GET /boards/items/{id}/values`, a coluna 456 traz o(s) `item_id` do(s) alvo(s).
3. **O target board pode ser identificado?** Sim, de forma determinística, por
   `settings.source_board_id` da coluna (a *value* carrega só `item_id`; o board vem da
   configuração da coluna, que é nossa e conhecida).
4. **Reconstruir `source → target` sem `/boards/{id}/links`?** Sim. `/boards/{id}/links` e
   `/mirror-values` seguem `403` para o token, mas são **desnecessários**: a relação sai
   inteira de `GET /boards/items/{id}/values`.
5. **Manter a relação só com os endpoints normais de items/values?** Sim — CRUD completo via
   `PATCH …/values/{col}` (grava) e `GET …/values` (lê).

→ **Relações funcionam NATIVAMENTE** via values. **Fallback local não é necessário** para
viabilizar o adapter. (A tabela de correspondência `monday_*_item_id ↔ sunday_*_item_id`
continua recomendável na Fase 2 apenas para **regravar chaves** na migração de dados — não
como substituta da relação nativa.) Classificação: **`A — FUNCIONA` (nativo)**.

### 10. Payload real aceito × formato retornado pelo GET (resumo)

| Tipo | Payload aceito (escrita) | Formato no GET |
|---|---|---|
| text (name) | `{"name": "<str>"}` no `PATCH` do item | `name: "<str>"` |
| number | `{"value": <int/float>}` | número (mesmo tipo) |
| status (sistema) | `{"status": "<key>"}` no `…/status` | `status: "<key>"` |
| date (sistema) | `{"target_date": "YYYY-MM-DD"}` no `PATCH` do item | ISO datetime `…T12:00:00.000Z` |
| checkbox | `{"value": true|false}` | booleano |
| link | `{"value": "<url>"}` | string idêntica |
| people (sistema) | `{"owner_user_id": "<id>"}` no `PATCH` do item | `owner_user_id: "<id>"` |
| board_relation | `{"value": {"links":[{"item_id":"<id>"}]}}` **ou** `{"value": "<id>"}` | igual ao enviado (`{links:[…]}` ou string) |

### 12–13. Quais values funcionam / não funcionam

- **Funcionam (dados):** texto/`name`, número, status, data, checkbox, link, people e
  `board_relation` — **todos** com round-trip confirmado.
- **Não funcionam para o token (todos de *schema*/config, não de *dados*):** criar/alterar
  coluna (`403`), renomear/mover/excluir grupo (`403`), editar/excluir comentário e anexo
  (`403`), upload binário de arquivo (`403`), `GET/POST /boards/{id}/links` e
  `/mirror-values` (`403`). Nenhum deles é de *value* e nenhum é requisito de GO (schema
  manual + anexo por link via Drive/GCS).

### 14–15. Relações nativas × fallback local

- **Nativas:** sim (ver Teste 10).
- **Fallback local:** **não necessário** para viabilidade. Permanece útil só como índice de
  regravação de chaves na migração (Fase 2) e como cache do N+1 de leitura de values.

### 16. Nova matriz A/B/C/D

Legenda — **A**: funciona nativamente · **B**: funciona com fallback local · **C**:
configuração manual aceitável (não bloqueante) · **D**: bloqueante.

| Capacidade | Classe | Evidência |
|---|---|---|
| Criar/ler/alterar/excluir **item** | **A** | `POST/PATCH/GET/DELETE` `201/200` (F0.14 + reteste) |
| **Values** de colunas custom (número, link, checkbox) | **A** | `PATCH …/values/{col}` + `GET …/values`, round-trip ok |
| **Campos de sistema** (texto/name, status, data, people) | **A** | `PATCH item` / `…/status`, round-trip ok |
| **Status** | **A** | `follow_up` gravado e relido |
| **Data** | **A** | grava `YYYY-MM-DD`, lê ISO datetime |
| **Checkbox / Link / Número** | **A** | round-trip exato |
| **People** | **A** | `owner_user_id` grava/relê (não bloqueante de qualquer modo) |
| **`board_relation`** | **A** | grava/relê via values; multi via `{links:[…]}`; sem `/links` |
| **Comentários** | **A** | criar/ler/excluir `201/200` (F0.14); editar `403` (não usado) |
| **Identificação de registros** (dedup) | **A/B** | `GET items` + `GET values` client-side; índice/cache local (F0.8) |
| Criar/alterar **schema** (colunas/grupos) | **C** | `403` — configuração manual 1×/board |
| **Arquivos** (upload binário) | **C** | `403`; anexo por **link** (`201`) via Drive/GCS |
| **Mirror** / `/links` (leitura) | **B** | `403` p/ token; espelho reconstruído no nosso código |
| **Search por valor de coluna** | **B** | sem server-side; índice local (F0.8) |
| **Webhook de saída** | **A/opcional** | ação `webhook` confirmada (F0.14); **polling** é a base |

### 17. Decisão final

> ## **GO** para implementar `sunday/client.py`.

Os requisitos essenciais de GO estão **todos** satisfeitos com os endpoints normais e o token
atual: CRUD de item, escrita/leitura de values de colunas existentes (custom **e** sistema),
comentários, identificação de registros e **relações nativas** (sem depender de `/links`).
Arquivos entram por link (Drive/GCS), mirror/search por lookup/índice local, e webhook é
opcional (polling é a arquitetura principal). A impossibilidade de criar *schema* via API é
**`C — configuração manual aceitável`** e **não** bloqueia.

### Ressalva de configuração (ação do time, não bloqueante)

A coluna `TESTE - RELAÇÃO` aponta para o board **79 ("Legal - Seguros")**, não para o **81**
como o enunciado pressupunha. A gravação/leitura funcionou mesmo assim (a API não valida o
board do alvo), mas, para a **UI do Sunday renderizar** o item vinculado, a coluna de
produção deve ter `source_board_id` **igual ao board realmente conectado**. Recomendação para
a configuração manual do schema (Fase 1): apontar cada `board_relation` para o board-alvo
correto (ex.: Prazos→Processos, Audiências→Processos, Controle→Contratos). Programaticamente,
a reconstrução `source → target` independe disso.

### Notas de implementação para `sunday/client.py`

- Resolver a rota de escrita **por coluna** via `GET /boards/{id}/columns` (`is_system`/
  `key`): sistema → `PATCH item`/`…/status`; custom → `…/values/{col}`.
- `board_relation`: usar sempre `{"value": {"links": [{"item_id": …}]}}` (suporta múltiplos
  alvos); ler de `GET …/values`. O board-alvo vem da configuração da coluna.
- Datas: enviar `YYYY-MM-DD`; ao ler, normalizar ISO datetime.
- People: `owner_user_id` no `PATCH` do item; `user_id` obtido de diretório/`/auth/me`.
- Leitura de values é **N+1** (1 chamada por item) — manter cache/índice local no polling.
