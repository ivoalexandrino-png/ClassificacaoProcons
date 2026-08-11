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

### Reteste Fase 0 — values de colunas pré-criadas manualmente + board_relation (sandbox 80/81, 2026-08-11)

**Contexto e decisão de arquitetura confirmada nesta rodada.** Um teste de escrita
anterior mostrou que o token de API do Sunday não consegue criar colunas
(`POST /boards/{id}/columns` → `403 Forbidden`, "requer login"). Isso foi formalmente
decidido como **não bloqueante**: o esquema/schema dos boards do Sunday é configurado
**manualmente** (login humano, uma vez por board); o adapter (`sunday/client.py`) só
precisa manipular **dados** (items/values/comentários) via API, nunca esquema. Este
reteste teve como único objetivo confirmar se o token grava e lê **values** de colunas
já configuradas manualmente, e se `board_relation` funciona nativamente ou exige
fallback. Script: `scripts/sunday_fase0_values_retest.py`. Relatório completo (sanitizado,
sem token nem PII): `docs/sunday-fase0-values-retest-report-2026-08-11.json`.

**Guard-rails respeitados:** escrita restrita aos boards `80` (`SANDBOX - API SUNDAY -
NÃO USAR`) e `81` (`SANDBOX - API SUNDAY - RELATION`); nome de cada board confirmado por
`GET /boards/{id}` antes de qualquer escrita; nenhuma coluna/grupo/board criado, alterado
ou excluído; dados 100% fictícios; token nunca impresso.

#### 1. Column IDs encontrados (board 80)

| Título solicitado | Título real (case como está no Sunday) | `column_id` | `key` | `type` | Natureza |
|---|---|---|---|---|---|
| TESTE - Texto | `TESTE - texto` | `443` | `name` | `text` | **coluna de sistema renomeada** (é o próprio nome/título do item, não uma coluna de texto dedicada) |
| TESTE - Número | `TESTE - Número` | `453` | `teste_numero` | `number` | coluna **customizada** nova |
| TESTE - Status | `Teste - Status` | `444` | `status` | `status` | **coluna de sistema renomeada**; opções vêm de `board.status_set` (`to_do`/`follow_up`/`done`), não de opções próprias da coluna |
| TESTE - Data | `teste - Data` | `446` | `target_date` | `date` | **coluna de sistema renomeada** |
| TESTE - Responsável | `teste - Responsável` | `445` | `owner` | `people` | **coluna de sistema renomeada** |
| TESTE - Link | `Teste - LINK` | `454` | `teste_link` | `link` | coluna **customizada** nova |
| TESTE - Checkbox | `TESTE - CHECKBOX` | `455` | `teste_checkbox` | `checkbox` | coluna **customizada** nova |
| TESTE - Relação | `TESTE - RELAÇÃO` | `456` | `teste_relacao` | `board_relation` | coluna **customizada** nova, **mal configurada** (ver §9) |

Achado relevante para o de-para (§7): a configuração manual **não recriou 4 colunas
novas** para Texto/Status/Data/Responsável — em vez disso **renomeou as colunas de
sistema já existentes** (`name`, `status`, `target_date`, `owner`). Isso funciona para o
adapter (o value É gravado e lido, ver §2–§6), mas muda a rota correta de escrita: nessas
4 colunas o value **não** passa por `/values/{column_id}` (essa rota responde `400
"System columns são atualizadas via PATCH /boards/items/:id."` para colunas de sistema,
reconfirmado nesta rodada) — é preciso usar `PATCH /boards/items/{id}` (ou
`/boards/items/{id}/status` para status). Só as 4 colunas realmente novas (Número, Link,
Checkbox, Relação) usam a rota `/values/{column_id}`.

#### 2. Resultado — Texto

**Funciona.** Como é a coluna de sistema `name`, a escrita é
`PATCH /boards/items/{id} {"name": "Teste Sunday API"}` → `200`; a releitura (via
`GET /boards/{id}/items` ou o próprio corpo do `PATCH`) confirma `"name": "Teste Sunday
API"`, idêntico ao valor enviado.

#### 3. Resultado — Número

**Funciona nativamente, confirmado de forma direta (não mais por inferência).**
`PATCH /boards/items/{id}/values/453 {"value": 12345}` → `200`, corpo
`{"id":"10626","item_id":"...","column_id":"453","value":12345,"updated_at":...,
"updated_by_user":"37"}`. A releitura via `GET /boards/items/{id}/values` devolve o
mesmo `value: 12345` (inteiro, sem coerção para string). Não existe
`GET /boards/items/{id}/values/{column_id}` (rota singular) — retorna `404`; a leitura
correta é sempre a rota plural, filtrando por `column_id` no array.

#### 4. Resultado — Status

**Funciona**, mas é a coluna de sistema `status`, não uma coluna de status customizada
com opções próprias. As opções reais vêm de `board.status_set` (descoberto via
`GET /boards/80`): `to_do` ("A fazer"), `follow_up` ("Follow-up"), `done` ("Feito").
Escrita testada com uma opção existente: `PATCH /boards/items/{id}/status {"status":
"to_do", "cascade": false}` → `200`; releitura confirma `"status": "to_do"`. Nenhuma key
foi inventada.

#### 5. Resultado — Data

**Funciona.** `PATCH /boards/items/{id} {"target_date": "2026-01-15"}` → `200`,
devolvendo `"target_date": "2026-01-15T12:00:00.000Z"`. Formato de retorno: ISO-8601
completo com hora fixada em `12:00:00.000Z` (meio-dia UTC) mesmo quando só a data foi
enviada — provavelmente para evitar que o fuso horário "empurre" a data para o dia
anterior/seguinte na renderização. A data em si (dia/mês/ano) é preservada exatamente.

#### 6. Resultado — Checkbox

**Funciona**, ida e volta nos dois sentidos. `PATCH /boards/items/{id}/values/455
{"value": true}` → `200`, releitura confirma `true`; depois `{"value": false}` → `200`,
releitura confirma `false`.

#### 7. Resultado — Link

**Funciona**, com uma observação de robustez: a API aceitou **dois formatos** sem
validar formato de URL nem impor um schema fixo — `{"value":
"https://example.com/teste-sunday-api"}` (string simples) e `{"value": {"url":
"https://example.com/teste-sunday-api-obj", "text": "teste"}}` (objeto com `url`/`text`,
formato tipo Monday) — os dois deram `200` e a releitura devolveu exatamente o que foi
enviado, sem coerção. **Implicação para o adapter**: como o Sunday não impõe um formato
único, `sunday/client.py` precisa fixar e documentar sua própria convenção (recomendado:
sempre gravar como objeto `{"url", "text"}`, que é mais informativo e compatível com o
padrão usado no Monday) para não gerar inconsistência entre o que o adapter escreve e o
que humanos gravam pela UI do Sunday.

#### 8. Resultado — People

**Funciona.** Fluxo seguido exatamente como pedido: o `user_id` do próprio usuário
autenticado foi obtido via `GET /auth/me` (nenhum ID foi inventado). Como
"Responsável"/`owner` também é coluna de sistema, a escrita foi
`PATCH /boards/items/{id} {"owner_user_id": "<id do usuário do token>"}` → `200`. A
resposta "enxuta" do `PATCH` não devolve `owner_user_id` no corpo, mas a releitura via
`GET /boards/80/items` (que devolve o item no formato "completo") confirma
`"owner_user_id"` gravado com o mesmo ID enviado. Nenhum erro ocorrido — não há HTTP/body
de erro a documentar aqui.

#### 9. Resultado — board_relation (Teste 10 — o mais importante)

**Bloqueado nesta sessão por um problema de configuração manual, não por limitação da
API — e por isso NÃO escrevemos nada nessa coluna.**

Ao ler `GET /boards/80/columns`, a coluna `TESTE - RELAÇÃO` (`id 456`, `type
board_relation`) tem `settings: {"source_board_id": "79"}`. O board `79` é
**`Legal - Seguros`** — um board de produção real, fora do sandbox autorizado — e não o
board `81` (`SANDBOX - API SUNDAY - RELATION`) exigido pela tarefa. Confirmado por
`GET /boards/79` (somente leitura, sem qualquer escrita) e por `GET /boards/81/columns`,
que mostra que o board 81 só tem colunas de sistema, sem nenhuma relação configurada de
volta para o 80.

Como a regra explícita desta tarefa é "Nenhum outro board pode sofrer escrita" e não há
garantia de que gravar um `item_id` nessa coluna não crie algum vínculo/registro do lado
do board 79 (produção), o script abortou esse subteste **antes de qualquer PATCH**,
registrou o achado no relatório e seguiu executando todos os outros testes normalmente.
Nenhuma escrita foi feita no board 79 nem em qualquer coluna `board_relation`.

Respostas objetivas às 5 perguntas do Teste 10, dado esse bloqueio:

1. **O Sunday aceitou gravar a relação?** Não testado — abortado por segurança antes do
   `PATCH`.
2. **O GET dos values devolve o `target_item_id`?** Não testado pelo mesmo motivo.
3. **O target board pode ser identificado?** **Sim** — e este é um achado novo e
   positivo: `GET /boards/{id}/columns` devolve `settings.source_board_id` para colunas
   `board_relation`, então o adapter consegue descobrir programaticamente para qual
   board uma coluna de relação aponta, sem precisar de `/links`.
4. **Conseguimos reconstruir `source item → target item` sem usar `/boards/{id}/links`?**
   Inconclusivo nesta sessão (não escrevemos o value). `/boards/{id}/links` continua
   retornando `403` para leitura e escrita (reconfirmado indiretamente: nenhuma mudança
   de permissão desde o teste anterior). Se `board_relation` funcionar via
   `/values/{column_id}` — o que é plausível dado que todas as outras colunas
   customizadas testadas nesta rodada (Número, Link, Checkbox) funcionaram sem exigir
   login — a resposta seria sim, sem depender de `/links`.
5. **Conseguimos manter a relação no futuro só com endpoints normais de items/values?**
   Mesma resposta do item 4: plausível, mas não confirmado diretamente nesta sessão.

**Ação recomendada (não bloqueante para a decisão de GO):** corrigir manualmente a
coluna `TESTE - RELAÇÃO` no Sunday para `source_board_id = 81` e reexecutar **somente**
o Teste 10 (`python scripts/sunday_fase0_values_retest.py`, que já contém a lógica —
volta a escrever automaticamente assim que o `source_board_id` bater com `81`).

**Avaliação do fallback (independente do resultado acima), conforme pedido:**

Tabela persistente proposta:

```
monday_source_item_id
monday_target_item_id
sunday_source_board_id
sunday_source_item_id
sunday_target_board_id
sunday_target_item_id
relation_type
```

Essa tabela é **suficiente** para os três relacionamentos do domínio legal:

- **Prazos → Processos**: relação N:1 simples (vários prazos apontam para um processo);
  uma linha por prazo com `relation_type="prazo_processo"` resolve consultas nos dois
  sentidos (join por `sunday_target_item_id` para "todos os prazos do processo X"; leitura
  direta por `sunday_source_item_id` para "processo do prazo Y").
- **Audiências → Processos**: mesmo padrão N:1; `relation_type="audiencia_processo"`.
- **Controle Assinaturas → Contratos**: mesmo padrão (a automação real "Assinado →
  cria item em Contratos" já é hoje uma automação do Monday que o **nosso próprio
  código** replicaria no cutover; a tabela local só precisa registrar o vínculo depois de
  criado, não decidir quando criar).

Nenhum dos três casos precisa de relação N:N nem de navegação reversa em tempo real via
API do Sunday — o polling do próprio adapter já lê os items nos dois boards
periodicamente, então a tabela local pode ser reconstruída/validada a cada ciclo.
**Classificação: B — FUNCIONA COM FALLBACK.** Isso vale **independentemente** de o
board_relation nativo funcionar ou não (a tabela não depende disso), e não é tratado como
bloqueante.

#### 10. Payload real aceito por tipo (resumo)

| Coluna | Rota de escrita | Payload aceito | Status |
|---|---|---|---|
| Texto (sistema `name`) | `PATCH /boards/items/{id}` | `{"name": "..."}` | `200` |
| Número (customizada) | `PATCH /boards/items/{id}/values/{colId}` | `{"value": 12345}` (inteiro) | `200` |
| Status (sistema) | `PATCH /boards/items/{id}/status` | `{"status": "<key do status_set>", "cascade": false}` | `200` |
| Data (sistema) | `PATCH /boards/items/{id}` | `{"target_date": "YYYY-MM-DD"}` | `200` |
| Checkbox (customizada) | `PATCH /boards/items/{id}/values/{colId}` | `{"value": true|false}` | `200` |
| Link (customizada) | `PATCH /boards/items/{id}/values/{colId}` | `{"value": "https://..."}` **ou** `{"value": {"url":"...","text":"..."}}` | `200` (os dois formatos) |
| People (sistema `owner`) | `PATCH /boards/items/{id}` | `{"owner_user_id": "<id>"}` | `200` |
| board_relation (customizada) | `PATCH /boards/items/{id}/values/{colId}` | não testado (bloqueado — ver §9) | — |

#### 11. Formato retornado pelo GET

- Colunas de sistema: só aparecem no corpo do próprio item
  (`GET /boards/{boardId}/items`, formato "completo": inclui `owner_user_id`,
  `creator_user_id`, `linked_user_id`, `assignee_user_ids`; o corpo de resposta do
  `PATCH` é uma versão "enxuta" sem esses campos de pessoas). Datas voltam em ISO-8601
  completo (`YYYY-MM-DDT12:00:00.000Z`).
- Colunas customizadas: `GET /boards/items/{id}/values` devolve um **array esparso**
  (só entra a coluna que já recebeu algum value) de objetos
  `{id, item_id, column_id, value, updated_at, updated_by_user}` — o `value` é devolvido
  exatamente no tipo/formato enviado (inteiro fica inteiro, string fica string, objeto
  fica objeto). Não existe rota singular `GET /boards/items/{id}/values/{columnId}`
  (`404`).

#### 12. Quais values funcionam

Texto (via nome do item), Número, Status (via rota de sistema), Data, Checkbox, Link
(dois formatos), People (via `owner_user_id`) — todos com escrita e releitura
confirmadas nesta sessão, mais Comentários (criação e leitura, ver §13).

#### 13. Quais não funcionam / não puderam ser confirmados

- **board_relation**: não escrito nesta sessão (coluna mal configurada, ver §9) — não é
  "não funciona", é "não testável em segurança com a configuração atual".
- Rota singular `GET /boards/items/{id}/values/{columnId}`: não existe (`404`); usar
  sempre a rota plural.
- `POST /boards/{id}/links` (rota alternativa de relação): continua bloqueada por
  permissão (`403`, "requer login") — já era assim em rodadas anteriores; o adapter não
  deve depender dela.
- Criação/alteração de colunas: continua bloqueada (`403`) — **decisão de arquitetura já
  tomada**: não é requisito para o GO, esquema é manual.

Extra confirmado fora do roteiro original mas essencial para a decisão (item 13 dos
critérios de GO — "comentários"): `POST /boards/items/{id}/comments` e
`GET /boards/items/{id}/comments` funcionam nativamente (`201`/`200`), com `mentions`
resolvido automaticamente quando o corpo contém uma menção.

#### 14. Relações — funcionam nativamente?

Não confirmado de forma direta nesta sessão (bloqueio de configuração, §9). Indícios
fortes de que sim: (a) o mesmo endpoint de values (`/values/{columnId}`) que funcionou
sem exigir login para Número/Link/Checkbox é a mesma rota documentada para
`board_relation`; (b) a coluna expõe `settings.source_board_id`, permitindo identificar o
board relacionado programaticamente. Falta confirmação direta do payload assim que a
coluna estiver com `source_board_id=81`.

#### 15. Fallback local seria necessário?

**Sim, como estratégia de arquitetura recomendada independentemente do resultado da
API nativa** — não porque a API comprovadamente falhe, mas porque (a) `/links` está
bloqueado para o token em qualquer cenário e (b) uma tabela local de-para é útil de
qualquer forma para rastreabilidade Monday↔Sunday durante a migração (§ "Estado de
deduplicação" mais acima neste documento). O fallback descrito no §9 é avaliado como
**suficiente** para os três casos de uso do domínio legal.

#### 16. Nova matriz A/B/C/D (A nativo · B fallback/transformação · C manual aceitável · D bloqueante)

| Requisito | Classe | Observação |
|---|---|---|
| Criar/ler/alterar item (nome, descrição, status, data, pessoa) | A | confirmado nesta rodada via `PATCH /boards/items/{id}` e `/status` |
| Escrever/ler values de colunas customizadas (número, checkbox, link) | A | confirmado **diretamente** nesta rodada — antes era só inferência |
| Comentários | A | criação e leitura confirmadas |
| Identificar registros (IDs de item/board estáveis) | A | `id` de item/board é string estável, devolvido em toda escrita/leitura |
| Esquema de colunas customizadas (criar/alterar) | C | bloqueado por token (`403`, requer login) — **decisão de arquitetura: configuração manual, não bloqueante** |
| `board_relation` nativo | B (fallback disponível; nativo pendente de reteste após correção de config) | coluna existe mas aponta para board errado (79 em vez de 81) nesta sandbox; fallback local (tabela de-para) avaliado como suficiente independente do resultado |
| `/boards/{id}/links` | B | bloqueado (`403`); adapter não depende dele — usa `/values` |
| Arquivos | B | upload binário bloqueado; anexo por link confirmado (`201`) → Drive/GCS + link |
| Mirror | B | lookup/cópia no código (não testado nesta rodada, fora de escopo) |
| Search | B | cache/índice local |
| Webhook | B (opcional) | polling é a arquitetura principal |
| — | **D: nenhum** | nada bloqueante identificado |

#### 17. Decisão final

**GO** para implementar `sunday/client.py`.

Justificativa direta: todos os requisitos essenciais listados no critério de decisão
desta tarefa foram confirmados nativamente nesta rodada — criação/leitura/alteração de
item; escrita/leitura de values de colunas existentes (customizadas **e** de sistema,
pela rota certa em cada caso); comentários; identificação de registros (IDs estáveis). O
único item sem confirmação direta é `board_relation`, e a própria tarefa definiu que,
nesse cenário, a resposta correta é avaliar o fallback e classificar como **B — funciona
com fallback**, não como bloqueante — o que foi feito no §9, com uma tabela local
avaliada como suficiente para os três relacionamentos reais do domínio (Prazos/Audiências
→ Processos, Controle Assinaturas → Contratos). A impossibilidade de criar colunas pela
API foi classificada, como instruído, como **C — configuração manual aceitável**, não
como bloqueante.

Ação de acompanhamento (não bloqueante, mas recomendada antes da Fase 1 avançar em
`board_relation`): pedir a correção manual de `source_board_id` na coluna `TESTE -
RELAÇÃO` (de `79` para `81`) e reexecutar o Teste 10 isoladamente para trocar a
classificação de B (fallback) para A (nativo confirmado), caso o payload realmente
funcione como esperado.

Ainda não implementado: `sunday/client.py`. Ainda não alterado: nenhum workflow. Ainda
não migrado: nenhum dado real.
