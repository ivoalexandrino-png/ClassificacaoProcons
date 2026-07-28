"""Cadastro de processo administrativo (PA) como item separado no Monday."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date

from classificacao_procons.email.gmail import GmailProconFetcher
from classificacao_procons.email.parser import extract_administrative_process_number
from classificacao_procons.models import ProcessedComplaint
from classificacao_procons.monday.client import (
    DEFAULT_BOARD_NAME,
    MondayClientError,
    MondayRegistrationResult,
    calculate_pa_response_deadline,
    create_item_update,
    find_item_id_by_protocol,
    get_api_token_from_env,
)
from classificacao_procons.monday.item_lookup import (
    load_monday_item_snapshot,
    register_standalone_pa_complaint,
)
from classificacao_procons.pa_cip_links import origin_cip_protocol_for_pa
from classificacao_procons.portal.procurador import (
    ProcuradorPortalError,
    fetch_pa_row_by_protocol,
)

ENV_PA_GROUP_NAME = "MONDAY_PA_GROUP_NAME"
DEFAULT_PA_GROUP_NAME = "Processos Administrativos"


def get_pa_group_name_from_env() -> str:
    value = os.environ.get(ENV_PA_GROUP_NAME, DEFAULT_PA_GROUP_NAME).strip()
    return value or DEFAULT_PA_GROUP_NAME


@dataclass(frozen=True)
class RelatedCipMatch:
    item_id: str
    protocol_number: str
    consumer_name: str
    consumer_cpf: str
    same_consumer_verified: bool
    verification_source: str


@dataclass(frozen=True)
class PaRegistrationContext:
    pa_protocol: str
    administrative_process_number: str | None
    related_cip: RelatedCipMatch | None


def find_pa_admin_number_in_gmail(
    fetcher: GmailProconFetcher,
    *,
    pa_protocol: str,
) -> str | None:
    """Busca e-mail de abertura de PA com o mesmo protocolo de atendimento."""
    base = pa_protocol.split("/", 1)[0]
    messages = fetcher.list_unread_notifications(
        max_results=10,
        query=f'subject:"Processo Administrativo Aberto" {base}',
    )
    for notification in messages:
        pa_number = extract_administrative_process_number(notification.subject)
        if pa_number and pa_number.endswith(base):
            return pa_number
    return None


def _normalize_cpf(value: str) -> str:
    return re.sub(r"\D", "", value)


def resolve_related_cip_item(
    *,
    api_token: str,
    pa_protocol: str,
    fetcher: GmailProconFetcher | None = None,
    board_name: str = DEFAULT_BOARD_NAME,
    portal_storage_path: str | None = None,
    pa_opened_on: date | None = None,
) -> RelatedCipMatch | None:
    """
    Localiza reclamação (CIP) anterior da mesma consumidora para reutilizar pasta Drive.

    Ordem: portal (CPF) → heurística PA gerado → Monday por CPF.
    """
    from classificacao_procons.monday.item_lookup import (
        find_item_id_by_consumer_cpf,
        find_related_cip_by_pa_conversion_heuristic,
        find_related_cip_by_pa_generated_heuristic,
        load_monday_item_snapshot,
        search_monday_items_by_name_contains,
    )

    origin_protocol = origin_cip_protocol_for_pa(pa_protocol)
    if origin_protocol:
        origin_item_id = find_item_id_by_protocol(
            api_token=api_token,
            protocol_number=origin_protocol,
            board_name=board_name,
        )
        if origin_item_id is not None:
            snapshot = load_monday_item_snapshot(api_token=api_token, item_id=origin_item_id)
            return RelatedCipMatch(
                item_id=origin_item_id,
                protocol_number=origin_protocol,
                consumer_name=snapshot.consumer_name,
                consumer_cpf=snapshot.consumer_cpf,
                same_consumer_verified=True,
                verification_source="declared_pa_cip_link",
            )

    consumer_cpf: str | None = None
    consumer_name: str | None = None
    source = ""

    storage = portal_storage_path or os.environ.get("PROCON_SP_STORAGE_STATE_PATH", "")
    if storage.strip():
        try:
            row = fetch_pa_row_by_protocol(
                pa_protocol,
                storage_state_path=storage.strip(),
                company_hint=os.environ.get("PROCON_SP_COMPANY_HINT", "B4A"),
            )
            consumer_cpf = row.consumer_cpf
            consumer_name = row.consumer_name
            source = "portal_procurador"
        except ProcuradorPortalError:
            pass

    if consumer_cpf is None:
        opened_on = pa_opened_on
        if opened_on is None and fetcher is not None:
            base = pa_protocol.split("/", 1)[0]
            messages = fetcher.list_unread_notifications(
                max_results=5,
                query=f'subject:"Processo Administrativo Aberto" {base}',
            )
            if messages:
                opened_on = messages[0].received_at.date()

        conversion = find_related_cip_by_pa_conversion_heuristic(
            api_token=api_token,
            pa_protocol=pa_protocol,
            pa_opened_on=opened_on,
            board_name=board_name,
        )
        if conversion is not None:
            item_id, protocol = conversion
            snapshot = load_monday_item_snapshot(api_token=api_token, item_id=item_id)
            return RelatedCipMatch(
                item_id=item_id,
                protocol_number=protocol or snapshot.protocol_number,
                consumer_name=snapshot.consumer_name,
                consumer_cpf=snapshot.consumer_cpf,
                same_consumer_verified=True,
                verification_source="pa_conversion_heuristic",
            )

        heuristic = find_related_cip_by_pa_generated_heuristic(
            api_token=api_token,
            pa_protocol=pa_protocol,
            board_name=board_name,
        )
        if heuristic is not None:
            item_id, protocol = heuristic
            snapshot = load_monday_item_snapshot(api_token=api_token, item_id=item_id)
            return RelatedCipMatch(
                item_id=item_id,
                protocol_number=protocol or snapshot.protocol_number,
                consumer_name=snapshot.consumer_name,
                consumer_cpf=snapshot.consumer_cpf,
                same_consumer_verified=True,
                verification_source="pa_generated_heuristic",
            )
        return None

    candidates = find_item_id_by_consumer_cpf(
        api_token=api_token,
        consumer_cpf=consumer_cpf,
        board_name=board_name,
        exclude_protocol=pa_protocol,
    )
    if len(candidates) == 1:
        item_id, protocol = candidates[0]
        snapshot = load_monday_item_snapshot(api_token=api_token, item_id=item_id)
        return RelatedCipMatch(
            item_id=item_id,
            protocol_number=protocol or snapshot.protocol_number,
            consumer_name=snapshot.consumer_name or consumer_name or "",
            consumer_cpf=consumer_cpf,
            same_consumer_verified=True,
            verification_source=source,
        )

    if consumer_name and len(candidates) != 1:
        name_hits = search_monday_items_by_name_contains(
            api_token=api_token,
            name_fragment=consumer_name.split()[0],
            board_name=board_name,
            exclude_protocol=pa_protocol,
        )
        if len(name_hits) == 1:
            item_id, protocol = name_hits[0]
            snapshot = load_monday_item_snapshot(api_token=api_token, item_id=item_id)
            if _normalize_cpf(snapshot.consumer_cpf) == _normalize_cpf(consumer_cpf):
                return RelatedCipMatch(
                    item_id=item_id,
                    protocol_number=protocol or snapshot.protocol_number,
                    consumer_name=snapshot.consumer_name,
                    consumer_cpf=consumer_cpf,
                    same_consumer_verified=True,
                    verification_source=f"{source}+name",
                )
    return None


def ensure_pa_monday_item_for_protocol(
    *,
    pa_protocol: str,
    api_token: str | None = None,
    board_name: str = DEFAULT_BOARD_NAME,
    pa_group_name: str | None = None,
    fetcher: GmailProconFetcher | None = None,
    related_cip: RelatedCipMatch | None = None,
    pa_opened_on: date | None = None,
) -> MondayRegistrationResult:
    """Cria item de PA no grupo de processos administrativos se ainda não existir."""
    token = api_token or get_api_token_from_env()
    if not token:
        raise MondayClientError("MONDAY_API_TOKEN não configurado.")

    existing = find_item_id_by_protocol(
        api_token=token,
        protocol_number=pa_protocol,
        board_name=board_name,
    )
    if existing is not None:
        return MondayRegistrationResult(
            item_id=existing,
            board_id="",
            item_url=None,
            skipped_duplicate=True,
        )

    admin_number: str | None = None
    if fetcher is not None:
        admin_number = find_pa_admin_number_in_gmail(fetcher, pa_protocol=pa_protocol)

    if related_cip is None:
        related_cip = resolve_related_cip_item(
            api_token=token,
            pa_protocol=pa_protocol,
            fetcher=fetcher,
            board_name=board_name,
            pa_opened_on=pa_opened_on,
        )

    if related_cip is None:
        raise MondayClientError(
            f"Não foi possível confirmar consumidora da CIP anterior para PA {pa_protocol}. "
            "Configure PROCON_SP_STORAGE_STATE_PATH (gov.br/procurador) "
            "ou cadastre manualmente.",
        )

    snapshot = load_monday_item_snapshot(api_token=token, item_id=related_cip.item_id)
    pa_deadline = calculate_pa_response_deadline()

    complaint = ProcessedComplaint(
        status="success",
        message_id="pa-standalone-register",
        access_code="",
        protocol_number=pa_protocol,
        consumer_name=snapshot.consumer_name or related_cip.consumer_name,
        consumer_cpf=snapshot.consumer_cpf or related_cip.consumer_cpf,
        complaint_date=snapshot.complaint_date,
        procon_response_deadline=None,
        sac_deadline=None,
        legal_deadline=None,
        cause=snapshot.cause,
        state=snapshot.state or "SP",
        pdf_url=snapshot.pdf_url,
        drive_folder_url=snapshot.drive_folder_url,
        notification_type="processo_administrativo",
        administrative_process_number=admin_number,
        pa_response_deadline=pa_deadline,
    )

    group = pa_group_name or get_pa_group_name_from_env()
    result = register_standalone_pa_complaint(
        complaint,
        api_token=token,
        board_name=board_name,
        group_name=group,
        related_cip_protocol=related_cip.protocol_number,
    )

    note = (
        f"PA {pa_protocol} cadastrado como caso separado (grupo {group}). "
        f"Mesma consumidora e pasta Drive da CIP {related_cip.protocol_number} "
        f"(verificação: {related_cip.verification_source})."
    )
    if admin_number:
        note += f" Nº processo administrativo: {admin_number}."
    create_item_update(api_token=token, item_id=result.item_id, body=note)
    create_item_update(
        api_token=token,
        item_id=related_cip.item_id,
        body=f"Vinculado ao PA {pa_protocol} (item separado no Monday).",
    )
    return result


def try_resolve_related_cip_for_known_consumer(
    *,
    api_token: str,
    pa_protocol: str,
    consumer_cpf: str,
    board_name: str = DEFAULT_BOARD_NAME,
) -> RelatedCipMatch | None:
    """Atalho quando o CPF da consumidora já é conhecido (ex.: caso mapeado)."""
    from classificacao_procons.monday.item_lookup import find_item_id_by_consumer_cpf

    candidates = find_item_id_by_consumer_cpf(
        api_token=api_token,
        consumer_cpf=consumer_cpf,
        board_name=board_name,
        exclude_protocol=pa_protocol,
    )
    if len(candidates) != 1:
        return None
    item_id, protocol = candidates[0]
    snapshot = load_monday_item_snapshot(api_token=api_token, item_id=item_id)
    return RelatedCipMatch(
        item_id=item_id,
        protocol_number=protocol or snapshot.protocol_number,
        consumer_name=snapshot.consumer_name,
        consumer_cpf=consumer_cpf,
        same_consumer_verified=True,
        verification_source="cpf_informado",
    )
