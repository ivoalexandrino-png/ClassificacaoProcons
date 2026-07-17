"""Cadastro/atualização de processos judiciais no Monday.com.

Um mesmo processo recebe várias intimações ao longo do tempo, então o item
do Monday é único por `numero_processo`: a primeira providência relevante
cria o item; as próximas apenas atualizam prazo, audiência, status e link.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from classificacao_procons.litigio.models import EventoProcesso
from classificacao_procons.litigio.monday_mapping import (
    build_column_values,
    find_processo_column,
)
from classificacao_procons.monday.client import (
    MondayClientError,
    _apply_complaint_column_values,
    _build_item_url,
    _create_item,
    _find_existing_item_id,
    _load_board_context,
    get_api_token_from_env,
)

DEFAULT_LITIGIO_BOARD_NAME = "processos judiciais"
DEFAULT_LITIGIO_GROUP_NAME = "acompanhamento"
ENV_LITIGIO_BOARD_NAME = "MONDAY_LITIGIO_BOARD_NAME"
ENV_LITIGIO_BOARD_ID = "MONDAY_LITIGIO_BOARD_ID"
ENV_LITIGIO_GROUP_NAME = "MONDAY_LITIGIO_GROUP_NAME"


@dataclass(frozen=True)
class MondayLitigioResult:
    item_id: str
    board_id: str
    item_url: str | None = None
    criado: bool = False


def get_litigio_board_name_from_env() -> str:
    return os.environ.get(ENV_LITIGIO_BOARD_NAME, DEFAULT_LITIGIO_BOARD_NAME).strip() or (
        DEFAULT_LITIGIO_BOARD_NAME
    )


def get_litigio_board_id_from_env() -> str | None:
    board_id = os.environ.get(ENV_LITIGIO_BOARD_ID, "").strip()
    return board_id or None


def get_litigio_group_name_from_env() -> str:
    return os.environ.get(ENV_LITIGIO_GROUP_NAME, DEFAULT_LITIGIO_GROUP_NAME).strip() or (
        DEFAULT_LITIGIO_GROUP_NAME
    )


def register_or_update_processo(
    evento: EventoProcesso,
    *,
    api_token: str | None = None,
    board_name: str | None = None,
    group_name: str | None = None,
    board_id: str | None = None,
) -> MondayLitigioResult | None:
    """Cria (ou atualiza) o item do processo no board de Litígio.

    Retorna `None` quando não há token do Monday configurado (o restante do
    pipeline continua funcionando; o cadastro no Monday é best-effort).
    """
    token = api_token or get_api_token_from_env()
    if not token:
        return None

    context = _load_board_context(
        api_token=token,
        board_name=board_name or get_litigio_board_name_from_env(),
        group_name=group_name or get_litigio_group_name_from_env(),
        board_id=board_id or get_litigio_board_id_from_env(),
    )

    column_values = build_column_values(context.columns, evento)

    processo_column = find_processo_column(context.columns)
    existing_item_id = None
    if processo_column is not None:
        existing_item_id = _find_existing_item_id(
            api_token=token,
            board_id=context.board_id,
            protocol_column=processo_column,
            protocol_number=evento.numero_processo_formatado,
        )

    if existing_item_id is not None:
        _apply_complaint_column_values(
            api_token=token,
            board_id=context.board_id,
            item_id=existing_item_id,
            column_details=context.column_details,
            column_values=column_values,
        )
        return MondayLitigioResult(
            item_id=existing_item_id,
            board_id=context.board_id,
            item_url=_build_item_url(
                account_slug=context.account_slug,
                board_id=context.board_id,
                item_id=existing_item_id,
            ),
            criado=False,
        )

    item_id = _create_item(
        api_token=token,
        board_id=context.board_id,
        group_id=context.group_id,
        item_name=evento.numero_processo_formatado,
    )
    _apply_complaint_column_values(
        api_token=token,
        board_id=context.board_id,
        item_id=item_id,
        column_details=context.column_details,
        column_values=column_values,
    )
    return MondayLitigioResult(
        item_id=item_id,
        board_id=context.board_id,
        item_url=_build_item_url(
            account_slug=context.account_slug,
            board_id=context.board_id,
            item_id=item_id,
        ),
        criado=True,
    )


__all__ = [
    "MondayClientError",
    "MondayLitigioResult",
    "register_or_update_processo",
]
