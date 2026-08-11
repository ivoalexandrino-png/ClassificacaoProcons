"""Modelos do Sunday — apenas os campos com contrato empiricamente confirmado (F0.13–F0.15).

Todos os IDs do Sunday são strings numéricas; nunca assumimos inteiro. Cada modelo
preserva o payload original em `raw` para não perder campos ainda não modelados.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

_DATE_PREFIX = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def parse_sunday_date(value: object) -> date | None:
    """Normaliza datas devolvidas pela API para `date` (sem horário).

    O Sunday normaliza datas escritas como `2026-01-15` para um datetime técnico em
    UTC (`2026-01-15T12:00:00.000Z`, meio-dia — confirmado na F0.15). O dia útil ao
    negócio é o prefixo da string; NÃO convertemos fuso (uma conversão para horário
    local poderia mudar o dia).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    match = _DATE_PREFIX.match(str(value).strip())
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def format_target_date(value: date | datetime | str) -> str:
    """Formata data para escrita (`YYYY-MM-DD`; datetimes ISO completos são aceitos)."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _sid(value: object) -> str | None:
    """ID do Sunday como string (nunca int)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class StatusOption:
    """Opção do `status_set` do board (status de sistema do item)."""

    key: str
    label: str
    color: str | None = None
    terminal: bool | None = None

    @classmethod
    def from_payload(cls, payload: dict) -> StatusOption:
        return cls(
            key=str(payload.get("key", "")),
            label=str(payload.get("label", "")),
            color=payload.get("color"),
            terminal=payload.get("terminal"),
        )


@dataclass(frozen=True)
class SundayUser:
    id: str
    name: str | None = None
    email: str | None = None
    access_level: str | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict) -> SundayUser:
        return cls(
            id=_sid(payload.get("id")) or "",
            name=payload.get("name"),
            email=payload.get("email"),
            access_level=payload.get("access_level"),
            raw=payload,
        )


@dataclass(frozen=True)
class Board:
    id: str
    name: str
    template_key: str | None = None
    hierarchy_depth: int | None = None
    status_set: tuple[StatusOption, ...] = ()
    area_options: tuple[str, ...] = ()
    capabilities: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict) -> Board:
        status_set = tuple(
            StatusOption.from_payload(option)
            for option in payload.get("status_set") or []
            if isinstance(option, dict)
        )
        return cls(
            id=_sid(payload.get("id")) or "",
            name=str(payload.get("name", "")),
            template_key=payload.get("template_key"),
            hierarchy_depth=payload.get("hierarchy_depth"),
            status_set=status_set,
            area_options=tuple(str(area) for area in payload.get("area_options") or []),
            capabilities=payload.get("capabilities") or {},
            raw=payload,
        )

    def status_keys(self) -> tuple[str, ...]:
        return tuple(option.key for option in self.status_set)


@dataclass(frozen=True)
class Group:
    id: str
    name: str
    color: str | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict) -> Group:
        return cls(
            id=_sid(payload.get("id")) or "",
            name=str(payload.get("name", "")),
            color=payload.get("color"),
            raw=payload,
        )


@dataclass(frozen=True)
class Column:
    """Coluna do board. Colunas de sistema têm rotas de escrita próprias (F0.15)."""

    id: str
    key: str | None
    label: str
    type: str
    is_system: bool
    settings: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict) -> Column:
        return cls(
            id=_sid(payload.get("id")) or "",
            key=payload.get("key"),
            label=str(payload.get("label", "")),
            type=str(payload.get("type", "")),
            is_system=bool(payload.get("is_system")),
            settings=payload.get("settings") or {},
            raw=payload,
        )

    @property
    def source_board_id(self) -> str | None:
        """Board-alvo configurado (colunas board_relation/mirror)."""
        return _sid(self.settings.get("source_board_id"))


@dataclass(frozen=True)
class Item:
    id: str
    board_id: str | None = None
    group_id: str | None = None
    parent_item_id: str | None = None
    name: str = ""
    description: str | None = None
    status: str | None = None
    target_date: str | None = None
    owner_user_id: str | None = None
    area: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict) -> Item:
        return cls(
            id=_sid(payload.get("id")) or "",
            board_id=_sid(payload.get("board_id")),
            group_id=_sid(payload.get("group_id")),
            parent_item_id=_sid(payload.get("parent_item_id")),
            name=str(payload.get("name", "")),
            description=payload.get("description"),
            status=payload.get("status"),
            target_date=payload.get("target_date"),
            owner_user_id=_sid(payload.get("owner_user_id")),
            area=payload.get("area"),
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
            raw=payload,
        )

    def target_date_as_date(self) -> date | None:
        return parse_sunday_date(self.target_date)


@dataclass(frozen=True)
class ItemValue:
    """Value de coluna customizada; `value` preserva o tipo JSON original."""

    id: str | None
    item_id: str | None
    column_id: str
    value: object
    updated_at: str | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict) -> ItemValue:
        return cls(
            id=_sid(payload.get("id")),
            item_id=_sid(payload.get("item_id")),
            column_id=_sid(payload.get("column_id")) or "",
            value=payload.get("value"),
            updated_at=payload.get("updated_at"),
            raw=payload,
        )


@dataclass(frozen=True)
class Comment:
    id: str
    body: str
    kind: str | None = None
    author_user_id: str | None = None
    created_at: str | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict) -> Comment:
        return cls(
            id=_sid(payload.get("id")) or "",
            body=str(payload.get("body", "")),
            kind=payload.get("kind"),
            author_user_id=_sid(
                payload.get("author_user_id")
                or payload.get("user_id")
                or payload.get("created_by_user_id"),
            ),
            created_at=payload.get("created_at"),
            raw=payload,
        )


@dataclass(frozen=True)
class Attachment:
    id: str
    url: str | None = None
    filename: str | None = None
    created_at: str | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict) -> Attachment:
        return cls(
            id=_sid(payload.get("id")) or "",
            url=payload.get("url"),
            filename=payload.get("filename") or payload.get("name"),
            created_at=payload.get("created_at"),
            raw=payload,
        )


@dataclass(frozen=True)
class WorkspaceBoardRef:
    """Vínculo workspace↔board. ATENÇÃO: `link_id` NÃO é board id (F0.13)."""

    link_id: str
    board_id: str
    name: str | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict) -> WorkspaceBoardRef:
        return cls(
            link_id=_sid(payload.get("id")) or "",
            board_id=_sid(payload.get("board_id")) or "",
            name=payload.get("name") or (payload.get("board") or {}).get("name"),
            raw=payload,
        )


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    boards: tuple[WorkspaceBoardRef, ...] = ()
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict) -> Workspace:
        boards = tuple(
            WorkspaceBoardRef.from_payload(ref)
            for ref in payload.get("boards") or []
            if isinstance(ref, dict)
        )
        return cls(
            id=_sid(payload.get("id")) or "",
            name=str(payload.get("name", "")),
            boards=boards,
            raw=payload,
        )


@dataclass(frozen=True)
class ItemsResult:
    """Resultado de listagem com suporte a ETag/304 (primitiva do polling)."""

    items: tuple[Item, ...]
    etag: str | None = None
    not_modified: bool = False


@dataclass(frozen=True)
class ValuesResult:
    values: tuple[ItemValue, ...]
    etag: str | None = None
    not_modified: bool = False


def normalize_relation_value(value: object) -> tuple[str, ...]:
    """Normaliza o value de uma coluna board_relation para uma tupla de item ids.

    Formatos aceitos (F0.15 + shape do frontend): `None`, `"7660"`,
    `["7654", "7664"]`, `{"item_id": "..."}` e `{"links": [{"item_id": "..."}]}`.
    """
    if value is None or value == "":
        return ()
    if isinstance(value, str | int):
        normalized = _sid(value)
        return (normalized,) if normalized else ()
    if isinstance(value, list):
        result = []
        for entry in value:
            if isinstance(entry, dict):
                entry = entry.get("item_id")
            normalized = _sid(entry)
            if normalized:
                result.append(normalized)
        return tuple(result)
    if isinstance(value, dict):
        if "links" in value:
            return normalize_relation_value(value.get("links"))
        return normalize_relation_value(value.get("item_id"))
    return ()
