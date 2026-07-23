"""Engrenagem entre quadros: intimações alimentam Processos Judiciais e KPIs.

O quadro "Processos Judiciais" é a origem/registro-mestre dos casos (citações
entram lá; automações do Monday alimentam o quadro de audiências a partir
dele). Este módulo faz cada intimação processada girar as outras engrenagens:

1. localiza o caso pelo número CNJ (Processos Judiciais ou Processos
   Trabalhista);
2. vincula os itens criados em prazos/audiências ao caso (conexão de quadros);
3. anota a intimação/análise na timeline do caso;
4. nos marcos de estágio (acordo, encerramento), atualiza o Status/Decisão do
   caso e a linha do processo no quadro "KPI - Processos Consumidores";
5. citação de processo inexistente cria o caso no quadro-mestre.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date

from classificacao_procons.juridico.models import ParsedIntimacao, Providencia
from classificacao_procons.juridico.monday import (
    _create_item,
    _create_update,
    _graphql_request,
    _list_all_boards,
    _normalize_title,
    _pick_juridico_board,
)
from classificacao_procons.juridico.providencias import (
    STAGE_ACORDO,
    STAGE_ENCERRAMENTO,
)
from classificacao_procons.monday.client import MondayClientError, get_api_token_from_env
from classificacao_procons.monday.mapping import allowed_labels

ENV_PROCESSOS_BOARD_ID = "MONDAY_PROCESSOS_BOARD_ID"
ENV_TRABALHISTA_BOARD_ID = "MONDAY_TRABALHISTA_BOARD_ID"
ENV_KPI_BOARD_ID = "MONDAY_KPI_BOARD_ID"

DEFAULT_PROCESSOS_BOARD_NAME = "processos judiciais"
DEFAULT_TRABALHISTA_BOARD_NAME = "processos trabalhista"
DEFAULT_KPI_BOARD_NAME = "kpi - processos consumidores"

# Grupo do quadro-mestre onde entram casos novos de consumidores.
DEFAULT_NEW_CASE_GROUP = "processos consumidores ativos"

CASE_SOURCE_JUDICIAL = "judicial"
CASE_SOURCE_TRABALHISTA = "trabalhista"

_TRABALHISTA_SEGMENT_DIGIT = "5"


@dataclass(frozen=True)
class CaseRef:
    """Item do caso no quadro-mestre."""

    board_id: str
    item_id: str
    item_name: str
    source: str
    created: bool = False


@dataclass
class CaseSyncResult:
    """Resultado da sincronização das engrenagens para uma intimação."""

    case: CaseRef | None = None
    actions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def note(self) -> str | None:
        parts = self.actions + [f"erro: {error}" for error in self.errors]
        return "; ".join(parts) or None


def _board_id_from_env_or_name(
    *,
    api_token: str,
    env_name: str,
    board_name: str,
) -> str | None:
    board_id = os.environ.get(env_name, "").strip()
    if board_id:
        return board_id
    board = _pick_juridico_board(_list_all_boards(api_token), board_name)
    return str(board["id"]) if board else None


def _board_columns_with_settings(api_token: str, board_id: str) -> list[dict]:
    data = _graphql_request(
        api_token=api_token,
        query="""
        query ($boardId: ID!) {
          boards(ids: [$boardId]) {
            columns { id title type settings_str }
            groups { id title }
          }
        }
        """,
        variables={"boardId": board_id},
    )
    boards = data.get("boards", [])
    return boards[0] if boards else {}


def _find_cnj_column(columns: list[dict]) -> dict | None:
    """Coluna de texto que guarda o número CNJ no quadro-mestre/KPI."""
    text_columns = [c for c in columns if c.get("type") in {"text", "long_text"}]
    for column in text_columns:
        normalized = _normalize_title(str(column.get("title", "")))
        if "processo" in normalized and "relacionado" not in normalized:
            return column
    for column in text_columns:
        if _normalize_title(str(column.get("title", ""))) in {"numero", "nº", "n"}:
            return column
    return None


def _find_status_column(columns: list[dict], title: str) -> dict | None:
    target = _normalize_title(title)
    for column in columns:
        if column.get("type") == "status" and _normalize_title(column.get("title", "")) == target:
            return column
    return None


def _find_date_column(columns: list[dict], title: str) -> dict | None:
    target = _normalize_title(title)
    for column in columns:
        if column.get("type") == "date" and _normalize_title(column.get("title", "")) == target:
            return column
    return None


def _search_case_in_board(
    *,
    api_token: str,
    board_id: str,
    cnj_column_id: str,
    process_number: str,
) -> dict | None:
    data = _graphql_request(
        api_token=api_token,
        query="""
        query ($boardId: ID!, $columnId: ID!, $value: CompareValue!) {
          boards(ids: [$boardId]) {
            items_page(
              limit: 5
              query_params: {
                rules: [{column_id: $columnId, compare_value: $value, operator: contains_text}]
              }
            ) {
              items { id name }
            }
          }
        }
        """,
        variables={"boardId": board_id, "columnId": cnj_column_id, "value": process_number},
    )
    boards = data.get("boards", [])
    items = boards[0].get("items_page", {}).get("items", []) if boards else []
    return items[0] if items else None


def is_trabalhista(process_number: str) -> bool:
    """Segmento J=5 na numeração única CNJ (Justiça do Trabalho)."""
    digits = "".join(char for char in process_number if char.isdigit())
    return len(digits) == 20 and digits[13] == _TRABALHISTA_SEGMENT_DIGIT


def find_case_item(
    process_number: str,
    *,
    api_token: str | None = None,
) -> CaseRef | None:
    """Localiza o caso pelo CNJ no quadro-mestre (judicial ou trabalhista)."""
    token = api_token or get_api_token_from_env()
    if not token:
        return None

    boards: list[tuple[str, str, str]] = []
    judicial_id = _board_id_from_env_or_name(
        api_token=token,
        env_name=ENV_PROCESSOS_BOARD_ID,
        board_name=DEFAULT_PROCESSOS_BOARD_NAME,
    )
    trabalhista_id = _board_id_from_env_or_name(
        api_token=token,
        env_name=ENV_TRABALHISTA_BOARD_ID,
        board_name=DEFAULT_TRABALHISTA_BOARD_NAME,
    )
    if is_trabalhista(process_number):
        if trabalhista_id:
            boards.append((trabalhista_id, CASE_SOURCE_TRABALHISTA, ""))
        if judicial_id:
            boards.append((judicial_id, CASE_SOURCE_JUDICIAL, ""))
    else:
        if judicial_id:
            boards.append((judicial_id, CASE_SOURCE_JUDICIAL, ""))
        if trabalhista_id:
            boards.append((trabalhista_id, CASE_SOURCE_TRABALHISTA, ""))

    for board_id, source, _ in boards:
        board = _board_columns_with_settings(token, board_id)
        cnj_column = _find_cnj_column(board.get("columns", []))
        if cnj_column is None:
            continue
        item = _search_case_in_board(
            api_token=token,
            board_id=board_id,
            cnj_column_id=str(cnj_column["id"]),
            process_number=process_number,
        )
        if item is not None:
            return CaseRef(
                board_id=board_id,
                item_id=str(item["id"]),
                item_name=str(item.get("name", "")),
                source=source,
            )
    return None


def create_case_for_citacao(
    intimacao: ParsedIntimacao,
    *,
    api_token: str,
    case_name: str | None = None,
) -> CaseRef | None:
    """Cria o caso no quadro-mestre quando uma citação chega sem registro.

    O quadro "Processos Judiciais" é a origem de casos novos; a citação é o
    evento que inaugura o caso. Processos trabalhistas não são criados
    automaticamente (estrutura do quadro é diferente e mais manual).
    """
    if is_trabalhista(intimacao.process_number):
        return None

    board_id = _board_id_from_env_or_name(
        api_token=api_token,
        env_name=ENV_PROCESSOS_BOARD_ID,
        board_name=DEFAULT_PROCESSOS_BOARD_NAME,
    )
    if not board_id:
        return None

    board = _board_columns_with_settings(api_token, board_id)
    groups = board.get("groups", [])
    group_id = None
    for group in groups:
        if _normalize_title(str(group.get("title", ""))) == DEFAULT_NEW_CASE_GROUP:
            group_id = str(group["id"])
            break
    if group_id is None and groups:
        group_id = str(groups[0]["id"])
    if group_id is None:
        return None

    item_name = case_name or f"Novo processo {intimacao.process_number}"
    item_id = _create_item(
        api_token=api_token,
        board_id=board_id,
        group_id=group_id,
        item_name=item_name,
    )

    cnj_column = _find_cnj_column(board.get("columns", []))
    if cnj_column is not None:
        value: object = intimacao.process_number
        if cnj_column.get("type") == "long_text":
            value = {"text": intimacao.process_number}
        _graphql_request(
            api_token=api_token,
            query="""
            mutation ($boardId: ID!, $itemId: ID!, $columnValues: JSON!) {
              change_multiple_column_values(
                board_id: $boardId
                item_id: $itemId
                column_values: $columnValues
              ) { id }
            }
            """,
            variables={
                "boardId": board_id,
                "itemId": item_id,
                "columnValues": json.dumps({str(cnj_column["id"]): value}),
            },
        )

    return CaseRef(
        board_id=board_id,
        item_id=item_id,
        item_name=item_name,
        source=CASE_SOURCE_JUDICIAL,
        created=True,
    )


def _find_relation_column_to_board(
    *,
    api_token: str,
    board_id: str,
    target_board_id: str,
) -> str | None:
    """Coluna de conexão (board_relation) que aponta para o quadro-mestre."""
    board = _board_columns_with_settings(api_token, board_id)
    for column in board.get("columns", []):
        if column.get("type") != "board_relation":
            continue
        try:
            settings = json.loads(column.get("settings_str") or "{}")
        except json.JSONDecodeError:
            continue
        board_ids = [str(value) for value in settings.get("boardIds", [])]
        if target_board_id in board_ids:
            return str(column["id"])
    return None


def link_item_to_case(
    *,
    api_token: str,
    board_id: str,
    item_id: str,
    case: CaseRef,
) -> bool:
    """Preenche a conexão de quadros do item (prazo/audiência) com o caso."""
    relation_column_id = _find_relation_column_to_board(
        api_token=api_token,
        board_id=board_id,
        target_board_id=case.board_id,
    )
    if relation_column_id is None:
        return False
    _graphql_request(
        api_token=api_token,
        query="""
        mutation ($boardId: ID!, $itemId: ID!, $columnValues: JSON!) {
          change_multiple_column_values(
            board_id: $boardId
            item_id: $itemId
            column_values: $columnValues
          ) { id }
        }
        """,
        variables={
            "boardId": board_id,
            "itemId": item_id,
            "columnValues": json.dumps(
                {relation_column_id: {"item_ids": [int(case.item_id)]}},
            ),
        },
    )
    return True


def _set_status_if_label_exists(
    *,
    api_token: str,
    board_id: str,
    item_id: str,
    column: dict,
    label: str,
) -> bool:
    allowed = allowed_labels(column.get("settings_str"), "status")
    if allowed is not None and label.casefold() not in allowed:
        return False
    _graphql_request(
        api_token=api_token,
        query="""
        mutation ($boardId: ID!, $itemId: ID!, $columnValues: JSON!) {
          change_multiple_column_values(
            board_id: $boardId
            item_id: $itemId
            column_values: $columnValues
          ) { id }
        }
        """,
        variables={
            "boardId": board_id,
            "itemId": item_id,
            "columnValues": json.dumps({str(column["id"]): {"label": label}}),
        },
    )
    return True


def update_case_for_stage(
    case: CaseRef,
    *,
    api_token: str,
    stage: str,
) -> list[str]:
    """Atualiza Status/Decisão do caso nos marcos inequívocos.

    Só marcos sem ambiguidade viram escrita automática: acordo homologado →
    Decisão Judicial "Acordo"; trânsito/arquivamento → Status "Encerrado".
    Sentenças não definem sozinhas o resultado (procedência de quem?) e ficam
    para revisão humana.
    """
    applied: list[str] = []
    board = _board_columns_with_settings(api_token, case.board_id)
    columns = board.get("columns", [])

    if stage == STAGE_ENCERRAMENTO:
        status_column = _find_status_column(columns, "Status")
        if status_column is not None and _set_status_if_label_exists(
            api_token=api_token,
            board_id=case.board_id,
            item_id=case.item_id,
            column=status_column,
            label="Encerrado",
        ):
            applied.append("caso: Status=Encerrado")

    if stage == STAGE_ACORDO:
        decisao_column = _find_status_column(columns, "Decisão Judicial")
        if decisao_column is not None and _set_status_if_label_exists(
            api_token=api_token,
            board_id=case.board_id,
            item_id=case.item_id,
            column=decisao_column,
            label="Acordo",
        ):
            applied.append("caso: Decisão Judicial=Acordo")

    return applied


def update_kpi_for_stage(
    process_number: str,
    *,
    api_token: str,
    stage: str,
    decision_date: date | None,
) -> list[str]:
    """Atualiza a linha do processo no quadro "KPI - Processos Consumidores".

    Acordo → Resultado "Acordo" (+ Data da Decisão); encerramento → Situação
    "Arquivado". Valores (condenação, pago, saving) seguem manuais: não vêm
    nos andamentos do DataJud. Linha inexistente não é criada (o KPI é
    curadoria do jurídico).
    """
    board_id = _board_id_from_env_or_name(
        api_token=api_token,
        env_name=ENV_KPI_BOARD_ID,
        board_name=DEFAULT_KPI_BOARD_NAME,
    )
    if not board_id:
        return []

    board = _board_columns_with_settings(api_token, board_id)
    columns = board.get("columns", [])
    cnj_column = _find_cnj_column(columns)
    if cnj_column is None:
        return []

    item = _search_case_in_board(
        api_token=api_token,
        board_id=board_id,
        cnj_column_id=str(cnj_column["id"]),
        process_number=process_number,
    )
    if item is None:
        return []

    item_id = str(item["id"])
    applied: list[str] = []

    if stage == STAGE_ACORDO:
        resultado = _find_status_column(columns, "Resultado")
        if resultado is not None and _set_status_if_label_exists(
            api_token=api_token,
            board_id=board_id,
            item_id=item_id,
            column=resultado,
            label="Acordo",
        ):
            applied.append("kpi: Resultado=Acordo")
        data_decisao = _find_date_column(columns, "Data da Decisão")
        if data_decisao is not None and decision_date is not None:
            _graphql_request(
                api_token=api_token,
                query="""
                mutation ($boardId: ID!, $itemId: ID!, $columnValues: JSON!) {
                  change_multiple_column_values(
                    board_id: $boardId
                    item_id: $itemId
                    column_values: $columnValues
                  ) { id }
                }
                """,
                variables={
                    "boardId": board_id,
                    "itemId": item_id,
                    "columnValues": json.dumps(
                        {str(data_decisao["id"]): {"date": decision_date.isoformat()}},
                    ),
                },
            )
            applied.append("kpi: Data da Decisão")

    if stage == STAGE_ENCERRAMENTO:
        situacao = _find_status_column(columns, "Situação")
        if situacao is not None and _set_status_if_label_exists(
            api_token=api_token,
            board_id=board_id,
            item_id=item_id,
            column=situacao,
            label="Arquivado",
        ):
            applied.append("kpi: Situação=Arquivado")

    return applied


def sync_case_boards(
    *,
    intimacao: ParsedIntimacao,
    providencia: Providencia,
    analysis: str | None,
    stage: str | None,
    stage_marker_date: date | None,
    prazo_board_id: str | None,
    prazo_item_id: str | None,
    audiencia_board_id: str | None,
    audiencia_item_id: str | None,
    api_token: str | None = None,
) -> CaseSyncResult:
    """Gira as engrenagens dos quadros-mestre a partir de uma intimação."""
    result = CaseSyncResult()
    token = api_token or get_api_token_from_env()
    if not token:
        return result

    try:
        case = find_case_item(intimacao.process_number, api_token=token)
        if case is None and intimacao.notification_type == "citacao":
            case = create_case_for_citacao(intimacao, api_token=token)
            if case is not None:
                result.actions.append("caso criado no quadro Processos Judiciais")
        result.case = case
        if case is None:
            result.actions.append("caso não encontrado no quadro-mestre")
            return result
    except MondayClientError as exc:
        result.errors.append(f"busca do caso: {exc}")
        return result

    for board_id, item_id, label in (
        (prazo_board_id, prazo_item_id, "prazo"),
        (audiencia_board_id, audiencia_item_id, "audiência"),
    ):
        if not board_id or not item_id:
            continue
        try:
            if link_item_to_case(
                api_token=token,
                board_id=board_id,
                item_id=item_id,
                case=case,
            ):
                result.actions.append(f"item de {label} conectado ao caso")
        except (MondayClientError, ValueError) as exc:
            result.errors.append(f"conexão do item de {label}: {exc}")

    try:
        body = (
            f"Intimação processada pelo agente jurídico — {providencia.description}."
            + (f"\n\n{analysis}" if analysis else "")
        )
        _create_update(api_token=token, item_id=case.item_id, body=body)
        result.actions.append("movimentação anotada no caso")
    except MondayClientError as exc:
        result.errors.append(f"anotação no caso: {exc}")

    if stage:
        try:
            result.actions.extend(
                update_case_for_stage(case, api_token=token, stage=stage),
            )
        except MondayClientError as exc:
            result.errors.append(f"atualização do caso: {exc}")
        if case.source == CASE_SOURCE_JUDICIAL:
            try:
                result.actions.extend(
                    update_kpi_for_stage(
                        intimacao.process_number,
                        api_token=token,
                        stage=stage,
                        decision_date=stage_marker_date,
                    ),
                )
            except MondayClientError as exc:
                result.errors.append(f"atualização do KPI: {exc}")

    return result
