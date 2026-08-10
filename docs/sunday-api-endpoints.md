# Sunday — referência da API REST (temas de legal)

> **Origem**: não há OpenAPI/Swagger exposto (todos os caminhos padrão — `/docs`, `/docs-json`,
> `/api-json`, `/swagger`, `/openapi.json`, … — retornam 404). Este mapa foi **reconstruído por
> engenharia reversa do front** (bundle Angular do `sunday.b4a.ai`) e **validado ao vivo** nas
> rotas de leitura. Tratar como **não oficial**: os campos dos corpos de criação (item/coluna/
> grupo) precisam de confirmação com o time do Sunday ou de teste em sandbox.

## Transporte e autenticação

- **Base da API**: valor do secret `SUNDAY_API_URL` (o serviço Cloud Run `sunday-api-*` da B4A;
  o mesmo `environment.apiBaseUrl` do front). Não versionar a URL literal — usar a variável.
- **Auth**: `Authorization: Bearer <PAT>` (Personal Access Token `sun_pat_…`). Token cru (estilo
  Monday) → `401`.
- **Escopos por token**: a API valida escopos por PAT. Ex.: `GET /boards/search` →
  `403 "Este token não tem o escopo \"search\" necessário"`. **As operações de escrita
  provavelmente exigem escopos específicos no PAT** — confirmar/gerar o token com os escopos certos.
- Content-Type: `application/json` (exceto upload de arquivo, que é `multipart/form-data`).
- Os PATs são gerenciados em `GET/POST/DELETE /auth/me/api-tokens`.

## Convenção de rotas

O controller de boards é **rooteado em `/boards`**. Recursos "filhos" identificados só por ID
não repetem o board: usam `/boards/items/{itemId}`, `/boards/columns/{columnId}`, etc.

## Boards

| Método | Rota | Uso |
|--------|------|-----|
| GET | `/boards` | lista boards (query `?workspace_id={id}`, `?archived=true`) |
| GET | `/boards/{boardId}` | detalhe do board (inclui `status_set`) |
| PATCH | `/boards/{boardId}` | atualiza board |
| POST | `/boards/{boardId}/archive` · `/unarchive` | arquivar/desarquivar |
| PATCH | `/boards/{boardId}/capabilities` · `/approvers` | configura board |
| POST/DELETE | `/boards/{boardId}/members` · `/members/{userId}` | membros (`{user_id}`) |

## Itens

| Método | Rota | Corpo / notas |
|--------|------|---------------|
| GET | `/boards/{boardId}/items` | **listar itens do board** |
| POST | `/boards/{boardId}/items` | **criar item** (corpo = DTO do item; campos a confirmar, ex.: `name`, `group_id`, valores) |
| GET | `/boards/items/{itemId}/values` | valores de coluna do item |
| PATCH | `/boards/items/{itemId}` | **editar item** (corpo = campos a alterar) |
| DELETE | `/boards/items/{itemId}` | **excluir item** |
| PATCH | `/boards/items/{itemId}/values/{columnKey}` | **atualizar valor de uma coluna**, corpo `{ "value": ... }` |
| PATCH | `/boards/items/{itemId}/status` | corpo `{ "status": "<key>", "cascade": false }` |
| PATCH | `/boards/items/{itemId}/group` | mover de grupo, corpo `{ "group_id": "<id>" }` |
| PATCH | `/boards/{boardId}/items/reorder` | corpo `{ "group_id", "ordered_ids": [] }` |
| POST | `/boards/items/{itemId}/push-forward` | corpo `{ "days": 7 }` |
| GET | `/boards/me/items` | itens do usuário (exige escopo) |

## Grupos

| Método | Rota | Corpo / notas |
|--------|------|---------------|
| GET | `/boards/{boardId}/groups` | listar grupos |
| POST | `/boards/{boardId}/groups` | criar grupo (corpo = DTO; ex.: `name`, `color`) |
| PATCH | `/boards/groups/{groupId}` | editar grupo |
| DELETE | `/boards/groups/{groupId}` | excluir grupo |
| PATCH | `/boards/{boardId}/groups/reorder` | corpo `{ "group_ids": [] }` |

## Colunas

| Método | Rota | Corpo / notas |
|--------|------|---------------|
| GET | `/boards/{boardId}/columns` | listar colunas (`{id,key,type,label,settings}`) |
| POST | `/boards/{boardId}/columns` | criar coluna (corpo = DTO; ex.: `key`, `type`, `label`, `settings`) |
| PATCH | `/boards/columns/{columnId}` | editar coluna |
| DELETE | `/boards/columns/{columnId}` | excluir coluna |
| PATCH | `/boards/{boardId}/columns/reorder` | corpo `{ "column_ids": [] }` |
| GET | `/boards/{boardId}/mirror-values` | query `?column_id=` (colunas espelho) |

## Comentários / updates

| Método | Rota | Corpo / notas |
|--------|------|---------------|
| GET | `/boards/items/{itemId}/comments` | listar comentários |
| POST | `/boards/items/{itemId}/comments` | corpo `{ "body", "kind": "reply", "mention_user_ids"?: [] }` |
| PATCH | `/boards/comments/{commentId}` | corpo `{ "body", "mention_user_ids"?: [] }` |
| DELETE | `/boards/comments/{commentId}` | excluir comentário |

## Anexos / arquivos

| Método | Rota | Corpo / notas |
|--------|------|---------------|
| GET | `/boards/items/{itemId}/attachments` | listar anexos |
| POST | `/boards/items/{itemId}/attachments/file` | **upload** `multipart/form-data`, campo `file` |
| POST | `/boards/items/{itemId}/attachments/link` | corpo `{ "url", "filename" }` |
| DELETE | `/boards/attachments/{attachmentId}` | excluir anexo |

## Outros (fora do escopo imediato da migração)

`GET /boards/search` (escopo `search`), `automations` (CRUD em `/boards/{id}/automations` e
`/boards/automations/{id}`), `views`, `links`, `calendar-anchor`, `context-doc`
(`PUT /boards/{id}/context-doc {content,filename}`), aprovações (`/items/{id}/approval/*`),
`ratings`, `notifications`, `bia/chat`, `auth/me` (+ `home-prefs`, `api-tokens`).

## Validações ao vivo (read-only, 2026-08-10)

- `GET /auth/me` → 200 (perfil).
- `GET /workspaces`, `/workspaces/22` → 200.
- `GET /boards`, `/boards?workspace_id=22`, `/boards?archived=true` → 200.
- `GET /boards/{id}`, `/boards/{id}/items|groups|columns` → 200.
- `GET /boards/search` → 403 (falta escopo `search` no PAT) — confirma a rota e o modelo de escopos.

## Pendências para escrita

1. Confirmar os **escopos necessários** no PAT para criar/editar/excluir (o token de leitura atual
   deu 403 em rotas com escopo).
2. Confirmar os **campos dos DTOs** de `POST /boards/{id}/items`, `/columns`, `/groups` (o front
   passa o objeto inteiro; os nomes de campo não aparecem minificados).
3. Testar num **board sandbox** antes de escrever nos boards legais reais.
