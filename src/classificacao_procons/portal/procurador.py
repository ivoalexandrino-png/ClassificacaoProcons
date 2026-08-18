"""Portal Procon-SP com login gov.br / procurador (sessão persistida)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from classificacao_procons.models import ProconComplaint
from classificacao_procons.portal.client import (
    PORTAL_LOGIN_URL,
    ProconPortalError,
    _download_pdf_from_documents_tab,
    _extract_complaint_from_page,
)

PA_LIST_URL_FRAGMENT = "/m/atendimentos"
ENV_STORAGE_PATH = "PROCON_SP_STORAGE_STATE_PATH"
ENV_STORAGE_JSON = "PROCON_SP_STORAGE_STATE_JSON"
DEFAULT_STORAGE_PATH = Path("credentials/procon-sp-storage.json")


class ProcuradorPortalError(ProconPortalError):
    """Erro ao navegar no portal como procurador."""


@dataclass(frozen=True)
class PaPortalRow:
    protocol_number: str
    consumer_name: str
    consumer_cpf: str
    complaint_date: date | None
    response_deadline: date | None
    administrative_process_number: str | None


def _parse_brazilian_date(value: str) -> date | None:
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", value)
    if not match:
        return None
    day, month, year = match.groups()
    return date(int(year), int(month), int(day))


def _normalize_cpf(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 11:
        return value.strip()
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def fetch_pa_row_by_protocol(
    protocol_number: str,
    *,
    storage_state_path: str,
    company_hint: str = "B4A",
    headless: bool = True,
) -> PaPortalRow:
    """
    Localiza linha em Processos administrativos (login já feito via storage_state).

    Requer arquivo JSON gerado com `playwright codegen` / sessão salva após gov.br.
    """
    state_path = Path(storage_state_path)
    if not state_path.is_file():
        raise ProcuradorPortalError(
            f"Storage state não encontrado: {storage_state_path}. "
            "Veja docs/procon-portal-procurador.md.",
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(state_path))
        page = context.new_page()
        try:
            page.goto(PORTAL_LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2000)

            company_select = page.locator("mat-select, select").filter(has_text=company_hint)
            if company_select.count():
                company_select.first.click()
                page.get_by_role("option", name=re.compile(company_hint, re.I)).first.click()
                page.wait_for_timeout(1500)

            pa_tab = page.get_by_role("tab", name=re.compile(r"Processos administrativos", re.I))
            if pa_tab.count():
                pa_tab.first.click()
                page.wait_for_timeout(2000)

            search = page.get_by_placeholder(
                re.compile(r"Filtrar por protocolo", re.I),
            )
            if search.count():
                search.first.fill(protocol_number)
                page.keyboard.press("Enter")
                page.wait_for_timeout(3000)

            row = page.locator("table tr", has_text=protocol_number.split("/")[0])
            if not row.count():
                raise ProcuradorPortalError(
                    f"Protocolo {protocol_number} não encontrado na lista de PA.",
                )

            cells = [cell.strip() for cell in row.first.inner_text().split("\n") if cell.strip()]
            consumer_name = cells[1] if len(cells) > 1 else ""
            cpf_match = re.search(r"\d{3}\.\d{3}\.\d{3}-\d{2}", row.first.inner_text())
            consumer_cpf = _normalize_cpf(cpf_match.group(0)) if cpf_match else ""

            body_text = row.first.inner_text()
            complaint_date = _parse_brazilian_date(body_text)
            deadline = None
            deadline_match = re.search(
                r"Prazo[:\s]*(\d{2}/\d{2}/\d{4})",
                body_text,
                re.I,
            )
            if deadline_match:
                deadline = _parse_brazilian_date(deadline_match.group(1))

            return PaPortalRow(
                protocol_number=protocol_number,
                consumer_name=consumer_name,
                consumer_cpf=consumer_cpf,
                complaint_date=complaint_date,
                response_deadline=deadline,
                administrative_process_number=None,
            )
        except PlaywrightTimeoutError as exc:
            raise ProcuradorPortalError("Timeout ao carregar processos administrativos.") from exc
        finally:
            context.close()
            browser.close()


def validate_storage_state_file(path: str) -> bool:
    """Retorna True se o JSON de storage state é legível."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and "cookies" in payload


def resolve_storage_state_path() -> str | None:
    """Resolve caminho do storage state (arquivo local ou JSON em env)."""
    configured = os.environ.get(ENV_STORAGE_PATH, "").strip()
    if configured and Path(configured).is_file():
        return configured

    if DEFAULT_STORAGE_PATH.is_file():
        return str(DEFAULT_STORAGE_PATH)

    raw_json = os.environ.get(ENV_STORAGE_JSON, "").strip()
    if raw_json:
        DEFAULT_STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_STORAGE_PATH.write_text(raw_json, encoding="utf-8")
        return str(DEFAULT_STORAGE_PATH)

    return None


def _select_company_if_needed(page: Page, company_hint: str) -> None:
    company_select = page.locator("mat-select, select").filter(has_text=company_hint)
    if company_select.count():
        company_select.first.click()
        page.get_by_role("option", name=re.compile(company_hint, re.I)).first.click()
        page.wait_for_timeout(1500)


def _open_reclamacao_by_protocol(page: Page, protocol_number: str) -> None:
    reclamacoes_tab = page.get_by_role("tab", name=re.compile(r"Reclamações", re.I))
    if reclamacoes_tab.count():
        reclamacoes_tab.first.click()
        page.wait_for_timeout(2000)

    search = page.get_by_placeholder(re.compile(r"Filtrar por protocolo", re.I))
    if search.count():
        search.first.fill(protocol_number)
        page.keyboard.press("Enter")
        page.wait_for_timeout(3000)

    protocol_fragment = protocol_number.split("/", 1)[0]
    row = page.locator("table tr", has_text=protocol_fragment)
    if not row.count():
        raise ProcuradorPortalError(
            f"Protocolo {protocol_number} não encontrado na lista de Reclamações.",
        )

    row.first.click()
    page.wait_for_timeout(3000)
    if PA_LIST_URL_FRAGMENT not in page.url:
        link = row.first.locator("a")
        if link.count():
            link.first.click()
            page.wait_for_timeout(3000)

    if PA_LIST_URL_FRAGMENT not in page.url:
        raise ProcuradorPortalError(
            f"Não foi possível abrir a reclamação {protocol_number} no portal.",
        )


def fetch_reclamacao_complaint_by_protocol(
    protocol_number: str,
    *,
    storage_state_path: str,
    download_dir: Path,
    company_hint: str = "B4A",
    headless: bool = True,
) -> ProconComplaint:
    """
    Abre reclamação pelo protocolo com sessão gov.br já salva (storage state).

    Usado quando o e-mail de Reclamação não traz código de acesso.
    """
    state_path = Path(storage_state_path)
    if not state_path.is_file():
        raise ProcuradorPortalError(
            f"Storage state não encontrado: {storage_state_path}. "
            "Veja docs/procon-portal-procurador.md.",
        )

    download_dir.mkdir(parents=True, exist_ok=True)
    safe_protocol = protocol_number.replace("/", "-")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(state_path))
        page = context.new_page()
        try:
            page.goto(PORTAL_LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2000)
            _select_company_if_needed(page, company_hint)
            _open_reclamacao_by_protocol(page, protocol_number)

            complaint = _extract_complaint_from_page(
                page,
                protocol_number,
                complaint_kind="reclamacao",
            )
            pdf_path = _download_pdf_from_documents_tab(
                page,
                download_dir,
                safe_protocol,
                complaint_kind="reclamacao",
            )
            if pdf_path:
                return ProconComplaint(
                    access_code=complaint.access_code,
                    consumer_name=complaint.consumer_name,
                    consumer_cpf=complaint.consumer_cpf,
                    cip_fa_number=complaint.cip_fa_number or protocol_number,
                    complaint_date=complaint.complaint_date,
                    response_deadline=complaint.response_deadline,
                    cause=complaint.cause,
                    state=complaint.state,
                    portal_url=complaint.portal_url,
                    pdf_path=pdf_path,
                    complaint_kind="reclamacao",
                    administrative_process_number=complaint.administrative_process_number,
                )
            return ProconComplaint(
                access_code=complaint.access_code,
                consumer_name=complaint.consumer_name,
                consumer_cpf=complaint.consumer_cpf,
                cip_fa_number=complaint.cip_fa_number or protocol_number,
                complaint_date=complaint.complaint_date,
                response_deadline=complaint.response_deadline,
                cause=complaint.cause,
                state=complaint.state,
                portal_url=complaint.portal_url,
                complaint_kind="reclamacao",
                administrative_process_number=complaint.administrative_process_number,
            )
        except PlaywrightTimeoutError as exc:
            raise ProcuradorPortalError(
                "Timeout ao abrir reclamação no portal Procon-SP.",
            ) from exc
        finally:
            context.close()
            browser.close()
