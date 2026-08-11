"""Cliente genérico da API do Sunday (V1).

Encapsula EXCLUSIVAMENTE os endpoints/payloads confirmados empiricamente na Fase 0
(`docs/migracao-monday-sunday-legal.md`, seções F0.13–F0.15). Não conhece domínios
(Procon/Jurídico/Contratos) nem boards reais; não executa migração.

Regras herdadas dos testes empíricos:

- IDs são sempre strings.
- `status` NUNCA via PATCH genérico (HTTP 200 com alteração ignorada) — somente
  `set_status()`, que usa a rota dedicada e valida a key contra o `status_set`.
- Colunas de sistema (`name`, `status`, `target_date`, `owner`, `area`) não passam
  pela rota de values (400 de negócio); usam `update_item()`/`set_status()`.
- `board_relation` grava por values, mas a API não valida o board-alvo — o client
  exige `expected_target_board_id` e rejeita divergência ANTES de chamar a API.
- Não existe GET de item individual (404): `get_item()` filtra a listagem do board.
- Escritas críticas aceitam `verify=True` (write → read → compare), porque HTTP 200
  isolado não prova persistência.
"""

from __future__ import annotations

from classificacao_procons.sunday.errors import (
    SundayNotFoundError,
    SundayRelationIntegrityError,
    SundayValidationError,
    SundayVerifyError,
)
from classificacao_procons.sunday.http import SundayConfig, SundayHttp, Transport
from classificacao_procons.sunday.models import (
    Attachment,
    Board,
    Column,
    Comment,
    Group,
    Item,
    ItemsResult,
    ItemValue,
    SundayUser,
    ValuesResult,
    Workspace,
    format_target_date,
    normalize_relation_value,
    parse_sunday_date,
)


class _Unset:
    def __repr__(self) -> str:
        return "<UNSET>"


UNSET = _Unset()

SYSTEM_FIELD_KEYS = ("name", "status", "target_date", "owner", "area")


class SundayClient:
    """Cliente V1 do Sunday. Genérico, sem hardcode de boards reais."""

    def __init__(self, config: SundayConfig | None = None, transport: Transport | None = None):
        self._http = SundayHttp(config or SundayConfig.from_env(), transport=transport)
        self._board_cache: dict[str, Board] = {}
        self._columns_cache: dict[str, dict[str, Column]] = {}

    def __repr__(self) -> str:  # nunca expõe o token
        return "SundayClient()"

    # ------------------------------------------------------------------ auth

    def get_me(self) -> SundayUser:
        """`GET /auth/me` — usuário dono do token."""
        response = self._http.request("GET", "/auth/me")
        return SundayUser.from_payload(response.body or {})

    def list_users_directory(self) -> list[SundayUser]:
        """`GET /users/directory` — base do de-para e-mail→user_id (people).

        Contém dados reais de pessoas; manter apenas em memória/cache local.
        """
        response = self._http.request("GET", "/users/directory")
        return [SundayUser.from_payload(user) for user in _as_list(response.body)]

    # -------------------------------------------------------------- metadata

    def list_boards(self) -> list[Board]:
        """`GET /boards` — boards acessíveis ao token (coleção completa)."""
        response = self._http.request("GET", "/boards")
        return [Board.from_payload(board) for board in _as_list(response.body)]

    def get_board(self, board_id: str, *, refresh: bool = False) -> Board:
        """`GET /boards/{id}` — metadata (inclui `status_set`); cacheada por board."""
        board_id = _require_id(board_id, "board_id")
        if refresh or board_id not in self._board_cache:
            response = self._http.request("GET", f"/boards/{board_id}")
            self._board_cache[board_id] = Board.from_payload(response.body or {})
        return self._board_cache[board_id]

    def get_workspace(self, workspace_id: str) -> Workspace:
        """`GET /workspaces/{id}` — inclui vínculos de board.

        ATENÇÃO (F0.13): em `boards[]`, `id` é o id do VÍNCULO workspace-board;
        o board real é `board_id`. Usar o vínculo como board id produz 403.
        """
        workspace_id = _require_id(workspace_id, "workspace_id")
        response = self._http.request("GET", f"/workspaces/{workspace_id}")
        return Workspace.from_payload(response.body or {})

    def list_groups(self, board_id: str) -> list[Group]:
        """`GET /boards/{id}/groups`."""
        board_id = _require_id(board_id, "board_id")
        response = self._http.request("GET", f"/boards/{board_id}/groups")
        return [Group.from_payload(group) for group in _as_list(response.body)]

    def create_group(self, board_id: str, name: str, *, color: str = "neutral") -> Group:
        """`POST /boards/{id}/groups {"name","color"}` (201).

        Renomear/excluir grupo é bloqueado para tokens (403) — acertar o nome na criação.
        """
        board_id = _require_id(board_id, "board_id")
        response = self._http.request(
            "POST",
            f"/boards/{board_id}/groups",
            json_body={"name": name, "color": color},
        )
        return Group.from_payload(response.body or {})

    def list_columns(self, board_id: str, *, refresh: bool = False) -> list[Column]:
        """`GET /boards/{id}/columns` — metadata de colunas; cacheada por board."""
        board_id = _require_id(board_id, "board_id")
        if refresh or board_id not in self._columns_cache:
            response = self._http.request("GET", f"/boards/{board_id}/columns")
            columns = [Column.from_payload(column) for column in _as_list(response.body)]
            self._columns_cache[board_id] = {column.id: column for column in columns}
        return list(self._columns_cache[board_id].values())

    def get_column(self, board_id: str, column_id: str, *, refresh: bool = False) -> Column:
        """Metadata de uma coluna (via listagem cacheada)."""
        column_id = _require_id(column_id, "column_id")
        self.list_columns(board_id, refresh=refresh)
        column = self._columns_cache[_require_id(board_id, "board_id")].get(column_id)
        if column is None:
            raise SundayNotFoundError(
                f"Coluna {column_id} não existe no board {board_id}.",
                path=f"/boards/{board_id}/columns",
            )
        return column

    # ----------------------------------------------------------------- items

    def list_items(self, board_id: str, *, etag: str | None = None) -> ItemsResult:
        """`GET /boards/{id}/items` — coleção completa (sem paginação; F0.13).

        Com `etag`, envia `If-None-Match`; 304 devolve `not_modified=True` e lista
        vazia (primitiva do polling barato de Contratos).
        """
        board_id = _require_id(board_id, "board_id")
        response = self._http.request("GET", f"/boards/{board_id}/items", etag=etag)
        if response.not_modified:
            return ItemsResult(items=(), etag=etag, not_modified=True)
        items = tuple(Item.from_payload(item) for item in _as_list(response.body))
        return ItemsResult(items=items, etag=response.etag)

    def get_item(self, board_id: str, item_id: str) -> Item | None:
        """Item individual via listagem do board (a API não tem GET de item — 404)."""
        item_id = _require_id(item_id, "item_id")
        for item in self.list_items(board_id).items:
            if item.id == item_id:
                return item
        return None

    def create_item(
        self,
        board_id: str,
        name: str,
        *,
        group_id: str | None = None,
        parent_item_id: str | None = None,
        description: str | None = None,
        target_date: object | None = None,
    ) -> Item:
        """`POST /boards/{id}/items` (201). Criar já no grupo certo: mover depois
        (`PATCH .../group`) é bloqueado para tokens (403, F0.14)."""
        board_id = _require_id(board_id, "board_id")
        payload: dict[str, object] = {"name": name}
        if group_id:
            payload["group_id"] = _require_id(group_id, "group_id")
        if parent_item_id:
            payload["parent_item_id"] = _require_id(parent_item_id, "parent_item_id")
        if description is not None:
            payload["description"] = description
        if target_date is not None:
            payload["target_date"] = format_target_date(target_date)  # type: ignore[arg-type]
        response = self._http.request("POST", f"/boards/{board_id}/items", json_body=payload)
        return Item.from_payload(response.body or {})

    def update_item(
        self,
        board_id: str,
        item_id: str,
        *,
        name: object = UNSET,
        description: object = UNSET,
        target_date: object = UNSET,
        owner_user_id: object = UNSET,
        area: object = UNSET,
        verify: bool = False,
    ) -> Item:
        """`PATCH /boards/items/{id}` — campos de sistema confirmados (F0.15).

        - `status` NÃO é aceito aqui (a API responde 200 e ignora em silêncio);
          use `set_status()`.
        - `area` só é enviada quando explicitamente informada — a coluna é
          estrutural e não deve ser alterada automaticamente.
        - `owner_user_id`: contrato aceito pela API, mas a troca efetiva entre
          usuários distintos ainda não foi totalmente validada (F0.15 — um único
          usuário disponível); não fazer lógica de domínio depender disso na V1.
        - `verify=True`: relê o item na listagem do board e compara os campos
          enviados (HTTP 200 não prova persistência).
        """
        item_id = _require_id(item_id, "item_id")
        payload: dict[str, object] = {}
        if name is not UNSET:
            payload["name"] = name
        if description is not UNSET:
            payload["description"] = description
        if target_date is not UNSET:
            payload["target_date"] = (
                None if target_date is None else format_target_date(target_date)  # type: ignore[arg-type]
            )
        if owner_user_id is not UNSET:
            payload["owner_user_id"] = (
                None if owner_user_id is None else _require_id(owner_user_id, "owner_user_id")
            )
        if area is not UNSET:
            payload["area"] = area
        if not payload:
            raise SundayValidationError("update_item sem nenhum campo para alterar.")
        response = self._http.request("PATCH", f"/boards/items/{item_id}", json_body=payload)
        updated = Item.from_payload(response.body or {})
        if verify:
            persisted = self.get_item(board_id, item_id)
            if persisted is None:
                raise SundayVerifyError(
                    f"Item {item_id} não encontrado na releitura do board {board_id}.",
                )
            self._verify_system_fields(payload, persisted)
            return persisted
        return updated

    def delete_item(self, item_id: str) -> None:
        """`DELETE /boards/items/{id}` (200)."""
        item_id = _require_id(item_id, "item_id")
        self._http.request("DELETE", f"/boards/items/{item_id}")

    # ---------------------------------------------------------------- status

    def set_status(
        self,
        board_id: str,
        item_id: str,
        status_key: str,
        *,
        cascade: bool = False,
        verify: bool = False,
    ) -> None:
        """`PATCH /boards/items/{id}/status {"status","cascade"}` — rota dedicada.

        Única forma suportada de alterar status (PATCH genérico ignora em
        silêncio). Valida `status_key` contra o `status_set` do board antes de
        enviar; com `verify=True`, relê e compara.
        """
        board_id = _require_id(board_id, "board_id")
        item_id = _require_id(item_id, "item_id")
        board = self.get_board(board_id)
        valid_keys = board.status_keys()
        if valid_keys and status_key not in valid_keys:
            raise SundayValidationError(
                f'Status "{status_key}" não existe no board {board_id}. '
                f"Keys válidas: {', '.join(valid_keys)}.",
            )
        self._http.request(
            "PATCH",
            f"/boards/items/{item_id}/status",
            json_body={"status": status_key, "cascade": cascade},
        )
        if verify:
            persisted = self.get_item(board_id, item_id)
            if persisted is None or persisted.status != status_key:
                raise SundayVerifyError(
                    f"Status do item {item_id} não persistiu: esperado "
                    f"{status_key!r}, lido {persisted.status if persisted else None!r}.",
                )

    # ---------------------------------------------------------------- values

    def list_values(self, item_id: str, *, etag: str | None = None) -> ValuesResult:
        """`GET /boards/items/{id}/values` — values das colunas customizadas."""
        item_id = _require_id(item_id, "item_id")
        response = self._http.request("GET", f"/boards/items/{item_id}/values", etag=etag)
        if response.not_modified:
            return ValuesResult(values=(), etag=etag, not_modified=True)
        values = tuple(ItemValue.from_payload(value) for value in _as_list(response.body))
        return ValuesResult(values=values, etag=response.etag)

    def get_value(self, item_id: str, column_id: str) -> object:
        """Value de uma coluna específica (tipo JSON preservado; None se ausente)."""
        column_id = _require_id(column_id, "column_id")
        for value in self.list_values(item_id).values:
            if value.column_id == column_id:
                return value.value
        return None

    def set_custom_value(
        self,
        board_id: str,
        item_id: str,
        column_id: str,
        value: object,
        *,
        verify: bool = False,
    ) -> None:
        """`PATCH /boards/items/{id}/values/{column_id} {"value": ...}`.

        Preserva o tipo JSON (string, número, booleano, null, lista — sem coerção
        para string; confirmado na F0.15). Colunas de SISTEMA são rejeitadas aqui
        antes da chamada (a API devolveria 400 de negócio): usar `update_item()` /
        `set_status()`.
        """
        board_id = _require_id(board_id, "board_id")
        item_id = _require_id(item_id, "item_id")
        column = self.get_column(board_id, column_id)
        if column.is_system or (column.key or "") in SYSTEM_FIELD_KEYS:
            raise SundayValidationError(
                f'Coluna {column.id} ("{column.label}") é de sistema — a API rejeita '
                "escrita via /values (400). Use update_item()/set_status().",
            )
        self._http.request(
            "PATCH",
            f"/boards/items/{item_id}/values/{column.id}",
            json_body={"value": value},
        )
        if verify:
            persisted = self.get_value(item_id, column.id)
            if persisted != value:
                raise SundayVerifyError(
                    f"Value da coluna {column.id} no item {item_id} não persistiu: "
                    f"esperado {value!r}, lido {persisted!r}.",
                )

    # ------------------------------------------------------------- relations

    def set_relation(
        self,
        board_id: str,
        item_id: str,
        column_id: str,
        target_item_ids: object,
        *,
        expected_target_board_id: str,
        verify: bool = False,
    ) -> None:
        """Grava relação board_relation por values (nativo, F0.15).

        Formatos: 1 alvo (string), vários alvos (lista) ou remoção (`None`/lista
        vazia → `null`).

        INTEGRIDADE OBRIGATÓRIA: a API aceita item de QUALQUER board (não valida
        contra `settings.source_board_id` — confirmado empiricamente). Por isso o
        chamador informa `expected_target_board_id` e o client compara com a
        configuração da coluna ANTES de gravar; divergência é erro, sem chamada.
        """
        board_id = _require_id(board_id, "board_id")
        item_id = _require_id(item_id, "item_id")
        expected = _require_id(expected_target_board_id, "expected_target_board_id")
        column = self.get_column(board_id, column_id)
        if column.type != "board_relation":
            raise SundayRelationIntegrityError(
                f'Coluna {column.id} ("{column.label}") tem tipo "{column.type}", '
                'não "board_relation".',
            )
        configured = column.source_board_id
        if configured is None:
            raise SundayRelationIntegrityError(
                f"Coluna {column.id} não tem settings.source_board_id configurado; "
                "corrija a coluna no app antes de gravar relações.",
            )
        if configured != expected:
            raise SundayRelationIntegrityError(
                f"Relação rejeitada: a coluna {column.id} aponta para o board "
                f"{configured}, mas o chamador espera o board {expected}. A API não "
                "faria esta validação — corrija a coluna ou o chamador.",
            )

        value: object
        normalized = _normalize_targets(target_item_ids)
        if not normalized:
            value = None
        elif len(normalized) == 1:
            value = normalized[0]
        else:
            value = list(normalized)
        self._http.request(
            "PATCH",
            f"/boards/items/{item_id}/values/{column.id}",
            json_body={"value": value},
        )
        if verify:
            persisted = normalize_relation_value(self.get_value(item_id, column.id))
            if set(persisted) != set(normalized):
                raise SundayVerifyError(
                    f"Relação da coluna {column.id} no item {item_id} não persistiu: "
                    f"esperado {sorted(normalized)}, lido {sorted(persisted)}.",
                )

    def get_relation(self, item_id: str, column_id: str) -> tuple[str, ...]:
        """Item ids relacionados, reconstruídos só por values (sem `/links` — 403)."""
        return normalize_relation_value(self.get_value(item_id, column_id))

    # ---------------------------------------------------------------- social

    def list_comments(self, item_id: str) -> list[Comment]:
        """`GET /boards/items/{id}/comments`."""
        item_id = _require_id(item_id, "item_id")
        response = self._http.request("GET", f"/boards/items/{item_id}/comments")
        return [Comment.from_payload(comment) for comment in _as_list(response.body)]

    def add_comment(
        self,
        item_id: str,
        body: str,
        *,
        kind: str = "reply",
        mention_user_ids: list[str] | None = None,
    ) -> Comment:
        """`POST /boards/items/{id}/comments {"body","kind"[,"mention_user_ids"]}`.

        Edição de comentário NÃO é exposta (PATCH → 403 para tokens, F0.14). O corpo
        chega pronto do chamador; transformações de migração (ex.: prefixo
        `[Monday · autor · data]`) pertencem à camada de migração.
        """
        item_id = _require_id(item_id, "item_id")
        payload: dict[str, object] = {"body": body, "kind": kind}
        if mention_user_ids:
            payload["mention_user_ids"] = [
                _require_id(user, "mention_user_id") for user in mention_user_ids
            ]
        response = self._http.request(
            "POST", f"/boards/items/{item_id}/comments", json_body=payload,
        )
        return Comment.from_payload(response.body or {})

    def delete_comment(self, comment_id: str) -> None:
        """`DELETE /boards/comments/{id}` (200)."""
        comment_id = _require_id(comment_id, "comment_id")
        self._http.request("DELETE", f"/boards/comments/{comment_id}")

    def list_attachments(self, item_id: str) -> list[Attachment]:
        """`GET /boards/items/{id}/attachments`."""
        item_id = _require_id(item_id, "item_id")
        response = self._http.request("GET", f"/boards/items/{item_id}/attachments")
        return [Attachment.from_payload(attachment) for attachment in _as_list(response.body)]

    def add_link_attachment(
        self,
        item_id: str,
        url: str,
        *,
        filename: str | None = None,
    ) -> Attachment:
        """`POST /boards/items/{id}/attachments/link {"url","filename"}` (201).

        Upload binário fica fora da V1 (403 para tokens): a arquitetura de arquivos
        é origem externa (Drive/GCS) → URL → anexo por link.
        """
        item_id = _require_id(item_id, "item_id")
        payload: dict[str, object] = {"url": url}
        if filename:
            payload["filename"] = filename
        response = self._http.request(
            "POST", f"/boards/items/{item_id}/attachments/link", json_body=payload,
        )
        return Attachment.from_payload(response.body or {})

    # -------------------------------------------------------------- internal

    def _verify_system_fields(self, sent: dict[str, object], persisted: Item) -> None:
        mismatches: list[str] = []
        for field_name, expected in sent.items():
            actual: object = getattr(persisted, field_name, None)
            if field_name == "target_date":
                expected_date = parse_sunday_date(expected)
                actual_date = parse_sunday_date(actual)
                if expected_date != actual_date:
                    mismatches.append(
                        f"target_date: esperado {expected_date}, lido {actual_date}",
                    )
                continue
            if expected is None:
                if actual not in (None, ""):
                    mismatches.append(f"{field_name}: esperado vazio, lido {actual!r}")
                continue
            if str(expected) != str(actual):
                mismatches.append(f"{field_name}: esperado {expected!r}, lido {actual!r}")
        if mismatches:
            raise SundayVerifyError(
                f"Item {persisted.id}: escrita respondeu 2xx mas não persistiu — "
                + "; ".join(mismatches),
            )


def _as_list(body: object) -> list[dict]:
    if isinstance(body, list):
        return [entry for entry in body if isinstance(entry, dict)]
    return []


def _require_id(value: object, label: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise SundayValidationError(f"{label} vazio ou ausente.")
    return text


def _normalize_targets(target_item_ids: object) -> tuple[str, ...]:
    if target_item_ids is None:
        return ()
    if isinstance(target_item_ids, str | int):
        return (_require_id(target_item_ids, "target_item_id"),)
    if isinstance(target_item_ids, list | tuple | set):
        return tuple(_require_id(entry, "target_item_id") for entry in target_item_ids)
    raise SundayValidationError(
        "target_item_ids deve ser None, um id (string) ou uma lista de ids.",
    )
