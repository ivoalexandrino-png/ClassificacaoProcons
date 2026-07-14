"""Fluxo automático: e-mail → portal → Drive."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from classificacao_procons.drive import DriveClientError, save_complaint_pdf
from classificacao_procons.email import GmailClientError, GmailProconFetcher
from classificacao_procons.google_auth import (
    DEFAULT_DRIVE_PARENT_FOLDER_ID,
    has_gmail_modify_access,
    has_valid_token,
)
from classificacao_procons.models import ProcessedComplaint, ProconNotificationEmail
from classificacao_procons.portal import PortalFetchOptions, ProconPortalError, fetch_complaint

DEFAULT_DOWNLOAD_DIR = Path("downloads")
DEFAULT_STATE_PATH = Path("data/processed-protocols.json")


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


def _resolve_protocol(notification: ProconNotificationEmail, complaint_protocol: str) -> str:
    if complaint_protocol:
        return complaint_protocol
    if notification.protocol_number:
        return notification.protocol_number
    return notification.access_code


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
            state="SP",
            pdf_url=None,
            drive_folder_url=None,
        )

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

    return ProcessedComplaint(
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
        state=complaint.state,
        pdf_url=drive_result.pdf_url,
        drive_folder_url=drive_result.consumer_folder_url,
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
        except (ProconPortalError, DriveClientError) as exc:
            result = ProcessedComplaint(
                status="error",
                message_id=notification.message_id,
                access_code=notification.access_code,
                protocol_number=notification.protocol_number or notification.access_code,
                consumer_name="",
                consumer_cpf="",
                complaint_date=None,
                procon_response_deadline=None,
                sac_deadline=None,
                legal_deadline=None,
                cause="",
                state="SP",
                pdf_url=None,
                drive_folder_url=None,
                error=str(exc),
            )

        results.append(result)

    return results
