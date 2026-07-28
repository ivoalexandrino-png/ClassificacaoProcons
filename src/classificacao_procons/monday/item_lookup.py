"""Consulta itens do board Procon no Monday."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

from classificacao_procons.models import ProcessedComplaint
from classificacao_procons.monday.client import (
    DEFAULT_BOARD_NAME,
    MondayClientError,
    MondayRegistrationResult,
    _apply_complaint_column_values,
    _build_item_url,
    _create_item,
    _graphql_request,
    _load_board_context,
    build_administrative_process_column_values,
    build_column_values,
    calculate_pa_response_deadline,
    find_column_by_field,
    find_protocol_column,
    get_api_token_from_env,
    get_board_id_from_env,
    get_board_name_from_env,
    get_origin_label_from_env,
    get_pa_generated_label_from_env,
    get_pa_responded_label_from_env,
    load_board_metadata,
    map_complaint_to_origin_label,
    sanitize_column_values,
)
from classificacao_procons.monday.mapping import (
    FIELD_CAUSE,
    FIELD_COMPLAINT_DATE,
    FIELD_CPF,
    FIELD_DOCS_SAC,
    FIELD_PA_GENERATED,
    FIELD_PDF_URL,
    FIELD_PROTOCOL,
    FIELD_STATE,
)


@dataclass(frozen=True)
class MondayItemSnapshot:
    consumer_name: str
    consumer_cpf: str
    protocol_number: str
    complaint_date: date | None
    cause: str
    state: str
    pdf_url: str | None
    drive_folder_url: str | None


def _normalize_cpf(value: str) -> str:
    return re.sub(r"\D", "", value)


def _parse_date_column(text: str) -> date | None:
    text = text.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _column_text_by_field(
    column_values: list[dict],
    columns_by_id: dict[str, str],
    field: str,
) -> str:
    from classificacao_procons.monday.mapping import MondayColumn, resolve_field_for_column

    for entry in column_values:
        column_id = entry.get("id", "")
        title = columns_by_id.get(column_id, "")
        if not title:
            continue
        column = MondayColumn(id=column_id, title=title, column_type=entry.get("type", ""))
        if resolve_field_for_column(column.title) == field:
            return (entry.get("text") or "").strip()
    return ""


def load_monday_item_snapshot(*, api_token: str, item_id: str) -> MondayItemSnapshot:
    context = load_board_metadata(api_token=api_token)
    columns_by_id = {column.id: column.title for column in context.columns}

    data = _graphql_request(
        api_token=api_token,
        query="""
        query ($itemId: [ID!]) {
          items(ids: $itemId) {
            id
            name
            column_values { id text value type }
          }
        }
        """,
        variables={"itemId": [item_id]},
    )
    items = data.get("items", [])
    if not items:
        raise MondayClientError(f"Item {item_id} não encontrado no Monday.")

    item = items[0]
    column_values = item.get("column_values", [])
    name = str(item.get("name", ""))

    return MondayItemSnapshot(
        consumer_name=name,
        consumer_cpf=_column_text_by_field(column_values, columns_by_id, FIELD_CPF),
        protocol_number=_column_text_by_field(column_values, columns_by_id, FIELD_PROTOCOL),
        complaint_date=_parse_date_column(
            _column_text_by_field(column_values, columns_by_id, FIELD_COMPLAINT_DATE),
        ),
        cause=_column_text_by_field(column_values, columns_by_id, FIELD_CAUSE),
        state=_column_text_by_field(column_values, columns_by_id, FIELD_STATE),
        pdf_url=_column_text_by_field(column_values, columns_by_id, FIELD_PDF_URL) or None,
        drive_folder_url=(
            _column_text_by_field(column_values, columns_by_id, FIELD_DOCS_SAC) or None
        ),
    )


def find_item_id_by_consumer_cpf(
    *,
    api_token: str,
    consumer_cpf: str,
    board_name: str = DEFAULT_BOARD_NAME,
    exclude_protocol: str | None = None,
) -> list[tuple[str, str]]:
    """Retorna [(item_id, protocol_number), ...] para o CPF informado."""
    normalized = _normalize_cpf(consumer_cpf)
    if len(normalized) != 11:
        return []

    context = load_board_metadata(api_token=api_token, board_name=board_name)
    cpf_column = find_column_by_field(context.columns, FIELD_CPF)
    if cpf_column is None:
        return []

    data = _graphql_request(
        api_token=api_token,
        query="""
        query ($boardId: ID!, $columnId: String!, $value: String!) {
          items_page_by_column_values(
            board_id: $boardId
            columns: [{column_id: $columnId, column_values: [$value]}]
            limit: 25
          ) {
            items { id name }
          }
        }
        """,
        variables={
            "boardId": context.board_id,
            "columnId": cpf_column.id,
            "value": normalized,
        },
    )
    items = data.get("items_page_by_column_values", {}).get("items", [])
    protocol_column = find_protocol_column(context.columns)
    results: list[tuple[str, str]] = []
    for entry in items:
        item_id = str(entry["id"])
        protocol = ""
        if protocol_column is not None:
            snapshot = load_monday_item_snapshot(api_token=api_token, item_id=item_id)
            protocol = snapshot.protocol_number
        if exclude_protocol and protocol == exclude_protocol:
            continue
        results.append((item_id, protocol))
    return results


def search_monday_items_by_name_contains(
    *,
    api_token: str,
    name_fragment: str,
    board_name: str = DEFAULT_BOARD_NAME,
    exclude_protocol: str | None = None,
) -> list[tuple[str, str]]:
    fragment = name_fragment.strip()
    if len(fragment) < 3:
        return []

    context = load_board_metadata(api_token=api_token, board_name=board_name)
    data = _graphql_request(
        api_token=api_token,
        query="""
        query ($boardId: ID!, $term: String!) {
          boards(ids: [$boardId]) {
            items_page(
              limit: 25
              query_params: {
                rules: [{
                  column_id: "name"
                  compare_value: [$term]
                  operator: contains_text
                }]
              }
            ) {
              items { id name }
            }
          }
        }
        """,
        variables={"boardId": context.board_id, "term": fragment},
    )
    boards = data.get("boards", [])
    if not boards:
        return []
    items = boards[0].get("items_page", {}).get("items", [])
    results: list[tuple[str, str]] = []
    for entry in items:
        item_id = str(entry["id"])
        snapshot = load_monday_item_snapshot(api_token=api_token, item_id=item_id)
        if exclude_protocol and snapshot.protocol_number == exclude_protocol:
            continue
        results.append((item_id, snapshot.protocol_number))
    return results


def find_related_cip_by_pa_conversion_heuristic(
    *,
    api_token: str,
    pa_protocol: str,
    pa_opened_on: date | None = None,
    board_name: str = DEFAULT_BOARD_NAME,
) -> tuple[str, str] | None:
    """
    CIP de origem quando PA converteu: mesmo consumidor (CPF único no board),
    PA=Sim, protocolo CIP NNNN/AAAA, data da reclamação anterior à abertura do PA.
    """
    context = load_board_metadata(api_token=api_token, board_name=board_name)
    pa_col = find_column_by_field(context.columns, FIELD_PA_GENERATED)
    cpf_col = find_column_by_field(context.columns, FIELD_CPF)
    proto_col = find_protocol_column(context.columns)
    complaint_col = find_column_by_field(context.columns, FIELD_COMPLAINT_DATE)
    if not all([pa_col, cpf_col, proto_col, complaint_col]):
        return None

    data = _graphql_request(
        api_token=api_token,
        query="""
        query ($boardId: ID!) {
          boards(ids: [$boardId]) {
            items_page(limit: 500) {
              items { id column_values { id text } }
            }
          }
        }
        """,
        variables={"boardId": context.board_id},
    )
    boards = data.get("boards", [])
    if not boards:
        return None

    rows: list[tuple[str, str, str, str, str]] = []
    for entry in boards[0].get("items_page", {}).get("items", []):
        texts = {cv["id"]: (cv.get("text") or "") for cv in entry.get("column_values", [])}
        rows.append(
            (
                str(entry["id"]),
                texts.get(proto_col.id, "").strip(),
                re.sub(r"\D", "", texts.get(cpf_col.id, "")),
                texts.get(pa_col.id, "").strip().lower(),
                texts.get(complaint_col.id, "").strip(),
            ),
        )

    cpf_counts = Counter(cpf for _, _, cpf, _, _ in rows if cpf)
    opened = pa_opened_on or date.today()
    matches: list[tuple[str, str]] = []

    for item_id, protocol, cpf, pa_flag, complaint_raw in rows:
        if not cpf or cpf_counts[cpf] != 1:
            continue
        if pa_flag not in {"sim", "yes"}:
            continue
        if protocol == pa_protocol:
            continue
        if not re.match(r"^\d+/\d{4}$", protocol):
            continue
        if not complaint_raw:
            continue
        complaint_date = _parse_date_column(complaint_raw)
        if complaint_date is None:
            continue
        if complaint_date >= opened:
            continue
        matches.append((item_id, protocol))

    if len(matches) == 1:
        return matches[0]

    if pa_opened_on is not None:
        relaxed: list[tuple[str, str]] = []
        for item_id, protocol, cpf, pa_flag, complaint_raw in rows:
            if not cpf:
                continue
            if pa_flag not in {"sim", "yes"}:
                continue
            if protocol == pa_protocol:
                continue
            if not re.match(r"^\d+/\d{4}$", protocol):
                continue
            complaint_date = _parse_date_column(complaint_raw)
            if complaint_date is None or complaint_date >= opened:
                continue
            relaxed.append((item_id, protocol))
        if len(relaxed) == 1:
            return relaxed[0]

    return None


def find_related_cip_by_pa_generated_heuristic(
    *,
    api_token: str,
    pa_protocol: str,
    board_name: str = DEFAULT_BOARD_NAME,
) -> tuple[str, str] | None:
    """
    Se exatamente um item (≠ protocolo PA) estiver com 'Gerou PA' = Sim, assume vínculo.
    """
    context = load_board_metadata(api_token=api_token, board_name=board_name)
    pa_generated_column = find_column_by_field(context.columns, FIELD_PA_GENERATED)
    protocol_column = find_protocol_column(context.columns)
    if pa_generated_column is None or protocol_column is None:
        return None

    data = _graphql_request(
        api_token=api_token,
        query="""
        query ($boardId: ID!) {
          boards(ids: [$boardId]) {
            items_page(limit: 500) {
              items {
                id
                column_values { id text }
              }
            }
          }
        }
        """,
        variables={"boardId": context.board_id},
    )
    boards = data.get("boards", [])
    if not boards:
        return None

    matches: list[tuple[str, str]] = []
    for entry in boards[0].get("items_page", {}).get("items", []):
        item_id = str(entry["id"])
        texts = {cv["id"]: (cv.get("text") or "") for cv in entry.get("column_values", [])}
        protocol = texts.get(protocol_column.id, "").strip()
        pa_flag = texts.get(pa_generated_column.id, "").strip().lower()
        if protocol == pa_protocol or not protocol:
            continue
        if pa_flag in {"sim", "yes"}:
            matches.append((item_id, protocol))

    if len(matches) == 1:
        return matches[0]
    return None


def register_standalone_pa_complaint(
    complaint: ProcessedComplaint,
    *,
    api_token: str | None = None,
    board_name: str = DEFAULT_BOARD_NAME,
    group_name: str,
    related_cip_protocol: str | None = None,
) -> MondayRegistrationResult:
    """Cria item de PA no grupo informado (protocolo = atendimento PA)."""
    token = api_token or get_api_token_from_env()
    if not token:
        raise MondayClientError("MONDAY_API_TOKEN não configurado.")

    context = _load_board_context(
        api_token=token,
        board_name=board_name or get_board_name_from_env(),
        group_name=group_name,
        board_id=get_board_id_from_env(),
    )

    protocol_column = find_protocol_column(context.columns)
    if protocol_column is not None:
        from classificacao_procons.monday.client import _find_existing_item_id

        existing = _find_existing_item_id(
            api_token=token,
            board_id=context.board_id,
            protocol_column=protocol_column,
            protocol_number=complaint.protocol_number,
        )
        if existing:
            return MondayRegistrationResult(
                item_id=existing,
                board_id=context.board_id,
                item_url=_build_item_url(
                    account_slug=context.account_slug,
                    board_id=context.board_id,
                    item_id=existing,
                ),
                skipped_duplicate=True,
            )

    column_values = sanitize_column_values(
        context.column_details,
        build_column_values(
            context.columns,
            consumer_name=complaint.consumer_name,
            state=complaint.state,
            pdf_url=complaint.pdf_url,
            protocol_number=complaint.protocol_number,
            consumer_cpf=complaint.consumer_cpf,
            complaint_date=complaint.complaint_date,
            sac_deadline=complaint.sac_deadline,
            legal_deadline=complaint.legal_deadline,
            cause=complaint.cause,
            origin_label=map_complaint_to_origin_label(
                complaint.cause,
                fallback=get_origin_label_from_env(),
            ),
        ),
    )

    pa_deadline = complaint.pa_response_deadline or calculate_pa_response_deadline()
    pa_values = build_administrative_process_column_values(
        context.columns,
        administrative_process_number=complaint.administrative_process_number or "",
        pa_response_deadline=pa_deadline,
        pa_generated_label=get_pa_generated_label_from_env(),
        pa_responded_label=get_pa_responded_label_from_env(),
    )
    column_values.update(sanitize_column_values(context.column_details, pa_values))

    docs_sac_column = find_column_by_field(context.columns, FIELD_DOCS_SAC)
    if docs_sac_column is not None and complaint.drive_folder_url:
        column_values[docs_sac_column.id] = complaint.drive_folder_url

    item_id = _create_item(
        api_token=token,
        board_id=context.board_id,
        group_id=context.group_id,
        item_name=complaint.consumer_name,
    )
    _apply_complaint_column_values(
        api_token=token,
        board_id=context.board_id,
        item_id=item_id,
        column_details=context.column_details,
        column_values=column_values,
    )

    if related_cip_protocol:
        from classificacao_procons.monday.client import create_item_update

        create_item_update(
            api_token=token,
            item_id=item_id,
            body=(
                f"CIP de origem (mesmos fatos): {related_cip_protocol}. "
                "Pasta Drive compartilhada com a reclamação anterior."
            ),
        )

    return MondayRegistrationResult(
        item_id=item_id,
        board_id=context.board_id,
        item_url=_build_item_url(
            account_slug=context.account_slug,
            board_id=context.board_id,
            item_id=item_id,
        ),
    )
