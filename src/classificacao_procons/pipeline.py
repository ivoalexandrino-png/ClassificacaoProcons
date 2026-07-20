"""Fluxo automático: e-mail → portal → Drive."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from classificacao_procons.campinas.deadlines import calculate_campinas_deadlines
from classificacao_procons.campinas.portal import (
    CampinasPortalError,
    CampinasPortalOptions,
    fetch_campinas_complaint,
)
from classificacao_procons.credentials import CredentialsError, resolve_portal_credentials
from classificacao_procons.drive import DriveClientError, save_complaint_pdf
from classificacao_procons.email.gmail import GmailClientError, GmailProconFetcher
from classificacao_procons.google_auth import (
    DEFAULT_DRIVE_PARENT_FOLDER_ID,
    has_gmail_modify_access,
    has_valid_token,
)
from classificacao_procons.models import ProcessedComplaint, ProconNotificationEmail
from classificacao_procons.monday import MondayClientError, register_complaint
from classificacao_procons.monday.client import (
    DEFAULT_BOARD_NAME,
    DEFAULT_GROUP_NAME,
    get_api_token_from_env,
)
from classificacao_procons.portal import PortalFetchOptions, ProconPortalError, fetch_complaint
from classificacao_procons.proconsumidor.portal import (
    ProconsumidorPortalError,
    ProconsumidorPortalOptions,
    fetch_proconsumidor_complaint,
)
from classificacao_procons.sc.attachments import ScAttachmentError, download_ssp_pdf_attachment
from classificacao_procons.sc.deadlines import calculate_sc_deadlines
from classificacao_procons.sc.pdf_parser import ScPdfParseError, parse_sc_ssp_pdf
from classificacao_procons.uberlandia.deadlines import calculate_uberlandia_deadlines
from classificacao_procons.uberlandia.portal import (
    UberlandiaPortalError,
    UberlandiaPortalOptions,
    fetch_uberlandia_complaint,
)

DEFAULT_DOWNLOAD_DIR = Path("downloads")
DEFAULT_STATE_PATH = Path("data/processed-protocols.json")
SOURCE_STATE_PREFIX = "source:"


class PipelineError(RuntimeError):
    """Erro geral no pipeline de processamento."""


@dataclass(frozen=True)
class PipelineOptions:
    max_results: int = 20
    download_dir: Path = DEFAULT_DOWNLOAD_DIR
    parent_folder_id: str = DEFAULT_DRIVE_PARENT_FOLDER_ID
    state_path: Path = DEFAULT_STATE_PATH
    mark_read: bool = True
    dry_run: bool = False
    credentials_path: str = "credentials/gmail-oauth.json"
    token_path: str = "credentials/gmail-token.json"
    monday_api_token: str | None = None
    monday_board_name: str = DEFAULT_BOARD_NAME
    monday_group_name: str = DEFAULT_GROUP_NAME
    register_on_monday: bool = True


def calculate_sac_and_legal_deadlines(*, base_date: date | None = None) -> tuple[date, date]:
    """SAC = +5 dias a partir do cadastro; jurídico = +1 dia após o SAC."""
    start = base_date or date.today()
    sac_deadline = start + timedelta(days=5)
    legal_deadline = sac_deadline + timedelta(days=1)
    return sac_deadline, legal_deadline


def _load_processed_protocols(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    protocols = data.get("protocols", [])
    return {str(item) for item in protocols}


def _save_processed_protocols(state_path: Path, protocols: set[str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"protocols": sorted(protocols)}
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _source_state_key(source_id: str, protocol_number: str) -> str:
    return f"{SOURCE_STATE_PREFIX}{source_id}:{protocol_number}"


def _resolve_state(notification: ProconNotificationEmail, complaint_state: str) -> str:
    if notification.state:
        return notification.state
    if complaint_state:
        return complaint_state
    if notification.source_id == "sp":
        return "SP"
    if notification.source_id == "sc":
        return "SC"
    if notification.source_id == "uberlandia":
        return "MG"
    return ""


def _resolve_protocol(notification: ProconNotificationEmail, complaint_protocol: str) -> str:
    if complaint_protocol:
        return complaint_protocol
    if notification.protocol_number:
        return notification.protocol_number
    return notification.access_code


def _resolve_monday_api_token(options: PipelineOptions) -> str | None:
    if options.monday_api_token:
        return options.monday_api_token
    return get_api_token_from_env()


def _register_on_monday_if_configured(
    result: ProcessedComplaint,
    *,
    options: PipelineOptions,
) -> ProcessedComplaint:
    if not options.register_on_monday or result.status != "success":
        return result

    api_token = _resolve_monday_api_token(options)
    if not api_token:
        return result

    try:
        monday_result = register_complaint(
            result,
            api_token=api_token,
            board_name=options.monday_board_name,
            group_name=options.monday_group_name,
        )
    except MondayClientError as exc:
        return replace(result, monday_error=str(exc))

    if monday_result is None:
        return result

    return replace(result, monday_item_url=monday_result.item_url)


def _process_sc_notification(
    notification: ProconNotificationEmail,
    *,
    options: PipelineOptions,
    processed_protocols: set[str],
    fetcher: GmailProconFetcher,
) -> ProcessedComplaint:
    protocol = notification.protocol_number or ""
    state_key = _source_state_key(notification.source_id, protocol)
    if state_key in processed_protocols:
        return ProcessedComplaint(
            status="skipped_duplicate",
            message_id=notification.message_id,
            access_code=protocol,
            protocol_number=protocol,
            consumer_name="",
            consumer_cpf="",
            complaint_date=None,
            procon_response_deadline=None,
            sac_deadline=None,
            legal_deadline=None,
            cause="",
            state=notification.state or "",
            pdf_url=None,
            drive_folder_url=None,
            error="Reclamação SC/SSP já processada anteriormente.",
        )

    payload = fetcher.fetch_message_payload(notification.message_id)
    pdf_path = download_ssp_pdf_attachment(
        fetcher._service,
        message_id=notification.message_id,
        payload=payload,
        download_dir=options.download_dir,
        protocol_number=protocol,
    )
    complaint = parse_sc_ssp_pdf(pdf_path)

    resolved_protocol = _resolve_protocol(notification, complaint.cip_fa_number)
    resolved_state = _resolve_state(notification, complaint.state)

    drive_result = save_complaint_pdf(
        consumer_name=complaint.consumer_name,
        pdf_path=pdf_path,
        cip_number=resolved_protocol,
        complaint_date=complaint.complaint_date,
        parent_folder_id=options.parent_folder_id,
        token_path=options.token_path,
    )

    receipt_date = notification.received_at.date()
    sac_deadline, legal_deadline, procon_deadline = calculate_sc_deadlines(
        received_date=receipt_date,
    )

    processed_protocols.add(state_key)
    _save_processed_protocols(options.state_path, processed_protocols)

    if options.mark_read and has_gmail_modify_access(options.token_path):
        fetcher.mark_as_read(notification.message_id)

    result = ProcessedComplaint(
        status="success",
        message_id=notification.message_id,
        access_code=protocol,
        protocol_number=resolved_protocol,
        consumer_name=complaint.consumer_name,
        consumer_cpf=complaint.consumer_cpf,
        complaint_date=complaint.complaint_date,
        procon_response_deadline=procon_deadline,
        sac_deadline=sac_deadline,
        legal_deadline=legal_deadline,
        cause=complaint.cause,
        state=resolved_state,
        pdf_url=drive_result.pdf_url,
        drive_folder_url=drive_result.consumer_folder_url,
    )
    return _register_on_monday_if_configured(result, options=options)


def _process_campinas_notification(
    notification: ProconNotificationEmail,
    *,
    options: PipelineOptions,
    processed_protocols: set[str],
    fetcher: GmailProconFetcher,
) -> ProcessedComplaint:
    protocol = notification.protocol_number or ""
    state_key = _source_state_key(notification.source_id, protocol)
    if state_key in processed_protocols:
        return ProcessedComplaint(
            status="skipped_duplicate",
            message_id=notification.message_id,
            access_code=protocol,
            protocol_number=protocol,
            consumer_name="",
            consumer_cpf="",
            complaint_date=None,
            procon_response_deadline=None,
            sac_deadline=None,
            legal_deadline=None,
            cause="",
            state=notification.state or "",
            pdf_url=None,
            drive_folder_url=None,
            error="Reclamação Campinas já processada anteriormente.",
        )

    api_token = _resolve_monday_api_token(options)
    try:
        portal_credentials = resolve_portal_credentials(
            "campinas",
            api_token=api_token,
        )
    except CredentialsError as exc:
        raise PipelineError(str(exc)) from exc

    complaint = fetch_campinas_complaint(
        CampinasPortalOptions(
            credentials=portal_credentials,
            protocol_number=protocol,
            download_dir=options.download_dir,
            consumer_name_hint=notification.consumer_name,
            consumer_cpf_hint=notification.consumer_cpf,
            complaint_date_hint=notification.complaint_date,
        ),
    )

    resolved_protocol = _resolve_protocol(notification, complaint.cip_fa_number)
    resolved_state = _resolve_state(notification, complaint.state)

    if not complaint.pdf_path:
        raise CampinasPortalError("PDF da reclamação não foi baixado do Procon Campinas.")

    drive_result = save_complaint_pdf(
        consumer_name=complaint.consumer_name,
        pdf_path=complaint.pdf_path,
        cip_number=resolved_protocol,
        complaint_date=complaint.complaint_date,
        parent_folder_id=options.parent_folder_id,
        token_path=options.token_path,
    )

    sac_deadline, legal_deadline = calculate_campinas_deadlines(
        base_date=complaint.complaint_date,
    )

    processed_protocols.add(state_key)
    _save_processed_protocols(options.state_path, processed_protocols)

    if options.mark_read and has_gmail_modify_access(options.token_path):
        fetcher.mark_as_read(notification.message_id)

    result = ProcessedComplaint(
        status="success",
        message_id=notification.message_id,
        access_code=protocol,
        protocol_number=resolved_protocol,
        consumer_name=complaint.consumer_name,
        consumer_cpf=complaint.consumer_cpf,
        complaint_date=complaint.complaint_date,
        procon_response_deadline=complaint.response_deadline,
        sac_deadline=sac_deadline,
        legal_deadline=legal_deadline,
        cause=complaint.cause,
        state=resolved_state,
        pdf_url=drive_result.pdf_url,
        drive_folder_url=drive_result.consumer_folder_url,
    )
    return _register_on_monday_if_configured(result, options=options)


def _process_uberlandia_notification(
    notification: ProconNotificationEmail,
    *,
    options: PipelineOptions,
    processed_protocols: set[str],
    fetcher: GmailProconFetcher,
) -> ProcessedComplaint:
    protocol = notification.protocol_number or ""
    state_key = _source_state_key(notification.source_id, protocol)
    if state_key in processed_protocols:
        return ProcessedComplaint(
            status="skipped_duplicate",
            message_id=notification.message_id,
            access_code=protocol,
            protocol_number=protocol,
            consumer_name="",
            consumer_cpf="",
            complaint_date=None,
            procon_response_deadline=None,
            sac_deadline=None,
            legal_deadline=None,
            cause="",
            state=notification.state or "",
            pdf_url=None,
            drive_folder_url=None,
            error="Reclamação Uberlândia já processada anteriormente.",
        )

    api_token = _resolve_monday_api_token(options)
    try:
        portal_credentials = resolve_portal_credentials(
            "uberlandia",
            api_token=api_token,
        )
    except CredentialsError as exc:
        raise PipelineError(str(exc)) from exc

    complaint = fetch_uberlandia_complaint(
        UberlandiaPortalOptions(
            credentials=portal_credentials,
            protocol_number=protocol,
            download_dir=options.download_dir,
            consumer_name_hint=notification.consumer_name,
            consumer_cpf_hint=notification.consumer_cpf,
            complaint_date_hint=notification.complaint_date,
            cause_hint=notification.cause,
        ),
    )

    resolved_protocol = _resolve_protocol(notification, complaint.cip_fa_number)
    resolved_state = _resolve_state(notification, complaint.state)
    resolved_cause = complaint.cause or notification.cause or ""

    if not complaint.pdf_path:
        raise UberlandiaPortalError(
            "PDF da reclamação não foi baixado do Fale Procon Uberlândia.",
        )

    drive_result = save_complaint_pdf(
        consumer_name=complaint.consumer_name or notification.consumer_name or "",
        pdf_path=complaint.pdf_path,
        cip_number=resolved_protocol,
        complaint_date=complaint.complaint_date or notification.complaint_date,
        parent_folder_id=options.parent_folder_id,
        token_path=options.token_path,
    )

    receipt_date = notification.received_at.date()
    sac_deadline, legal_deadline = calculate_uberlandia_deadlines(base_date=receipt_date)

    processed_protocols.add(state_key)
    _save_processed_protocols(options.state_path, processed_protocols)

    if options.mark_read and has_gmail_modify_access(options.token_path):
        fetcher.mark_as_read(notification.message_id)

    result = ProcessedComplaint(
        status="success",
        message_id=notification.message_id,
        access_code=protocol,
        protocol_number=resolved_protocol,
        consumer_name=complaint.consumer_name or notification.consumer_name or "",
        consumer_cpf=complaint.consumer_cpf or notification.consumer_cpf or "",
        complaint_date=complaint.complaint_date or notification.complaint_date,
        procon_response_deadline=complaint.response_deadline,
        sac_deadline=sac_deadline,
        legal_deadline=legal_deadline,
        cause=resolved_cause,
        state=resolved_state,
        pdf_url=drive_result.pdf_url,
        drive_folder_url=drive_result.consumer_folder_url,
    )
    return _register_on_monday_if_configured(result, options=options)


def _process_proconsumidor_notification(
    notification: ProconNotificationEmail,
    *,
    options: PipelineOptions,
    processed_protocols: set[str],
    fetcher: GmailProconFetcher,
) -> ProcessedComplaint:
    protocol = notification.protocol_number or ""
    state_key = _source_state_key(notification.source_id, protocol)
    if state_key in processed_protocols:
        return ProcessedComplaint(
            status="skipped_duplicate",
            message_id=notification.message_id,
            access_code=protocol,
            protocol_number=protocol,
            consumer_name="",
            consumer_cpf="",
            complaint_date=None,
            procon_response_deadline=None,
            sac_deadline=None,
            legal_deadline=None,
            cause="",
            state=notification.state or "",
            pdf_url=None,
            drive_folder_url=None,
            error="Reclamação Proconsumidor já processada anteriormente.",
        )

    api_token = _resolve_monday_api_token(options)
    try:
        portal_credentials = resolve_portal_credentials(
            "proconsumidor",
            api_token=api_token,
        )
    except CredentialsError as exc:
        raise PipelineError(str(exc)) from exc

    complaint = fetch_proconsumidor_complaint(
        ProconsumidorPortalOptions(
            credentials=portal_credentials,
            complaint_number=protocol,
            download_dir=options.download_dir,
        ),
    )

    resolved_protocol = _resolve_protocol(notification, complaint.cip_fa_number)
    resolved_state = _resolve_state(notification, complaint.state)

    if not complaint.pdf_path:
        raise ProconsumidorPortalError("PDF da reclamação não foi baixado do Proconsumidor.")

    drive_result = save_complaint_pdf(
        consumer_name=complaint.consumer_name,
        pdf_path=complaint.pdf_path,
        cip_number=resolved_protocol,
        complaint_date=complaint.complaint_date,
        parent_folder_id=options.parent_folder_id,
        token_path=options.token_path,
    )

    sac_deadline, legal_deadline = calculate_sac_and_legal_deadlines()

    processed_protocols.add(state_key)
    _save_processed_protocols(options.state_path, processed_protocols)

    if options.mark_read and has_gmail_modify_access(options.token_path):
        fetcher.mark_as_read(notification.message_id)

    result = ProcessedComplaint(
        status="success",
        message_id=notification.message_id,
        access_code=protocol,
        protocol_number=resolved_protocol,
        consumer_name=complaint.consumer_name,
        consumer_cpf=complaint.consumer_cpf,
        complaint_date=complaint.complaint_date,
        procon_response_deadline=complaint.response_deadline,
        sac_deadline=sac_deadline,
        legal_deadline=legal_deadline,
        cause=complaint.cause,
        state=resolved_state,
        pdf_url=drive_result.pdf_url,
        drive_folder_url=drive_result.consumer_folder_url,
    )
    return _register_on_monday_if_configured(result, options=options)


def _process_sp_notification(
    notification: ProconNotificationEmail,
    *,
    options: PipelineOptions,
    processed_protocols: set[str],
    fetcher: GmailProconFetcher,
) -> ProcessedComplaint:
    complaint = fetch_complaint(
        PortalFetchOptions(
            access_code=notification.access_code,
            download_dir=options.download_dir,
        ),
    )

    protocol = _resolve_protocol(notification, complaint.cip_fa_number)
    if protocol in processed_protocols:
        return ProcessedComplaint(
            status="skipped_duplicate",
            message_id=notification.message_id,
            access_code=notification.access_code,
            protocol_number=protocol,
            consumer_name=complaint.consumer_name,
            consumer_cpf=complaint.consumer_cpf,
            complaint_date=complaint.complaint_date,
            procon_response_deadline=complaint.response_deadline,
            sac_deadline=None,
            legal_deadline=None,
            cause=complaint.cause,
            state=complaint.state,
            pdf_url=None,
            drive_folder_url=None,
            error="Protocolo já processado anteriormente.",
        )

    if not complaint.pdf_path:
        raise ProconPortalError("PDF da reclamação não foi baixado do portal.")

    drive_result = save_complaint_pdf(
        consumer_name=complaint.consumer_name,
        pdf_path=complaint.pdf_path,
        cip_number=protocol,
        complaint_date=complaint.complaint_date,
        parent_folder_id=options.parent_folder_id,
        token_path=options.token_path,
    )

    sac_deadline, legal_deadline = calculate_sac_and_legal_deadlines()

    processed_protocols.add(protocol)
    _save_processed_protocols(options.state_path, processed_protocols)

    if options.mark_read and has_gmail_modify_access(options.token_path):
        fetcher.mark_as_read(notification.message_id)

    result = ProcessedComplaint(
        status="success",
        message_id=notification.message_id,
        access_code=notification.access_code,
        protocol_number=protocol,
        consumer_name=complaint.consumer_name,
        consumer_cpf=complaint.consumer_cpf,
        complaint_date=complaint.complaint_date,
        procon_response_deadline=complaint.response_deadline,
        sac_deadline=sac_deadline,
        legal_deadline=legal_deadline,
        cause=complaint.cause,
        state=_resolve_state(notification, complaint.state),
        pdf_url=drive_result.pdf_url,
        drive_folder_url=drive_result.consumer_folder_url,
    )
    return _register_on_monday_if_configured(result, options=options)


def _process_notification(
    notification: ProconNotificationEmail,
    *,
    options: PipelineOptions,
    processed_protocols: set[str],
    fetcher: GmailProconFetcher,
) -> ProcessedComplaint:
    if options.dry_run:
        protocol = notification.protocol_number or notification.access_code
        return ProcessedComplaint(
            status="dry_run",
            message_id=notification.message_id,
            access_code=notification.access_code,
            protocol_number=protocol,
            consumer_name="",
            consumer_cpf="",
            complaint_date=None,
            procon_response_deadline=None,
            sac_deadline=None,
            legal_deadline=None,
            cause="",
            state=notification.state or _resolve_state(notification, ""),
            pdf_url=None,
            drive_folder_url=None,
        )

    if notification.source_id == "proconsumidor":
        return _process_proconsumidor_notification(
            notification,
            options=options,
            processed_protocols=processed_protocols,
            fetcher=fetcher,
        )

    if notification.source_id == "campinas":
        return _process_campinas_notification(
            notification,
            options=options,
            processed_protocols=processed_protocols,
            fetcher=fetcher,
        )

    if notification.source_id == "sc":
        return _process_sc_notification(
            notification,
            options=options,
            processed_protocols=processed_protocols,
            fetcher=fetcher,
        )

    if notification.source_id == "uberlandia":
        return _process_uberlandia_notification(
            notification,
            options=options,
            processed_protocols=processed_protocols,
            fetcher=fetcher,
        )

    return _process_sp_notification(
        notification,
        options=options,
        processed_protocols=processed_protocols,
        fetcher=fetcher,
    )


def process_new_complaints(options: PipelineOptions | None = None) -> list[ProcessedComplaint]:
    """Processa e-mails não lidos do Procon: portal + Drive."""
    options = options or PipelineOptions()

    if not options.dry_run and not has_valid_token(options.token_path):
        raise PipelineError("Google não conectado. Rode: procon-email auth")

    fetcher = GmailProconFetcher.from_credentials(
        credentials_path=options.credentials_path,
        token_path=options.token_path,
    )

    try:
        notifications = fetcher.list_unread_notifications(max_results=options.max_results)
    except GmailClientError as exc:
        raise PipelineError(str(exc)) from exc

    processed_protocols = _load_processed_protocols(options.state_path)
    results: list[ProcessedComplaint] = []

    for notification in notifications:
        try:
            result = _process_notification(
                notification,
                options=options,
                processed_protocols=processed_protocols,
                fetcher=fetcher,
            )
        except (
            ProconPortalError,
            ProconsumidorPortalError,
            CampinasPortalError,
            UberlandiaPortalError,
            ScAttachmentError,
            ScPdfParseError,
            DriveClientError,
            PlaywrightTimeoutError,
            PipelineError,
        ) as exc:
            result = ProcessedComplaint(
                status="error",
                message_id=notification.message_id,
                access_code=notification.access_code or notification.protocol_number or "",
                protocol_number=notification.protocol_number or notification.access_code or "",
                consumer_name="",
                consumer_cpf="",
                complaint_date=None,
                procon_response_deadline=None,
                sac_deadline=None,
                legal_deadline=None,
                cause="",
                state=notification.state or "",
                pdf_url=None,
                drive_folder_url=None,
                error=str(exc),
            )

        results.append(result)

    return results


def register_monday_for_access_code(
    access_code: str,
    *,
    options: PipelineOptions | None = None,
) -> ProcessedComplaint:
    """Cadastra no Monday um caso já salvo no Drive (recuperação manual)."""
    from classificacao_procons.drive.client import _build_drive_service, ensure_consumer_folder
    from classificacao_procons.drive.reader import _find_complaint_pdf, _list_children

    options = options or PipelineOptions()

    if not has_valid_token(options.token_path):
        raise PipelineError("Google não conectado. Rode: procon-email auth")

    complaint = fetch_complaint(
        PortalFetchOptions(
            access_code=access_code,
            download_dir=options.download_dir,
        ),
    )
    protocol = complaint.cip_fa_number or access_code

    service = _build_drive_service(options.token_path)
    _folder_id, folder_url = ensure_consumer_folder(
        service,
        parent_folder_id=options.parent_folder_id,
        consumer_name=complaint.consumer_name,
    )
    children = _list_children(service, folder_id=_folder_id)
    complaint_pdf = _find_complaint_pdf(children)
    if complaint_pdf is None or not complaint_pdf.web_view_link:
        raise PipelineError(
            f"PDF da reclamação não encontrado no Drive para {complaint.consumer_name}.",
        )

    sac_deadline, legal_deadline = calculate_sac_and_legal_deadlines(
        base_date=complaint.complaint_date,
    )
    result = ProcessedComplaint(
        status="success",
        message_id="manual-register",
        access_code=access_code,
        protocol_number=protocol,
        consumer_name=complaint.consumer_name,
        consumer_cpf=complaint.consumer_cpf,
        complaint_date=complaint.complaint_date,
        procon_response_deadline=complaint.response_deadline,
        sac_deadline=sac_deadline,
        legal_deadline=legal_deadline,
        cause=complaint.cause,
        state=complaint.state,
        pdf_url=complaint_pdf.web_view_link,
        drive_folder_url=folder_url,
    )
    registered = _register_on_monday_if_configured(result, options=options)
    if registered.monday_error:
        raise PipelineError(registered.monday_error)
    if registered.monday_item_url is None:
        raise PipelineError("Monday não configurado ou item não criado.")
    return registered
