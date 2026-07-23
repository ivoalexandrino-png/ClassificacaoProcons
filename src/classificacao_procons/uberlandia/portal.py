"""Cliente do portal Fale Procon Uberlândia via Playwright."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Final

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from classificacao_procons.credentials.models import PortalCredentials
from classificacao_procons.models import ProconComplaint
from classificacao_procons.uberlandia.email_parser import UBERLANDIA_STATE_LABEL

DEFAULT_TIMEOUT_MS: Final = 90_000
PAGE_LOAD_WAIT_UNTIL: Final = "domcontentloaded"


class UberlandiaPortalError(RuntimeError):
    """Erro ao acessar ou extrair dados do Fale Procon Uberlândia."""


@dataclass(frozen=True)
class UberlandiaPortalOptions:
    credentials: PortalCredentials
    protocol_number: str
    download_dir: Path
    consumer_name_hint: str | None = None
    consumer_cpf_hint: str | None = None
    complaint_date_hint: date | None = None
    cause_hint: str | None = None
    headless: bool = True


def _parse_brazilian_date(value: str) -> date | None:
    value = value.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_cpf(value: str) -> str:
    return re.sub(r"\D", "", value)


def _fill_login_fields(page: Page, *, login: str, password: str) -> None:
    login_filled = False
    for selector in (
        "input[name*='login' i]",
        "input[id*='login' i]",
        "input[name*='usuario' i]",
        "input[id*='usuario' i]",
        "input[type='email']",
        "input[type='text']",
    ):
        locator = page.locator(selector)
        if locator.count():
            locator.first.fill(login)
            login_filled = True
            break
    if not login_filled:
        raise UberlandiaPortalError("Campo de login não encontrado no portal Uberlândia.")

    password_input = page.locator("input[type='password']")
    if not password_input.count():
        raise UberlandiaPortalError("Campo de senha não encontrado no portal Uberlândia.")
    password_input.first.fill(password)


def _submit_login(page: Page) -> None:
    for label in ("Entrar", "Acessar", "Login", "Validar"):
        button = page.locator("button", has_text=label)
        if button.count():
            button.first.click()
            page.wait_for_timeout(4000)
            return
    page.locator("input[type='submit']").first.click()
    page.wait_for_timeout(4000)


def _open_protocol(page: Page, protocol_number: str) -> bool:
    for placeholder in ("Protocolo", "Processo", "Número", "Numero", "Pesquisar"):
        locator = page.get_by_placeholder(placeholder)
        if locator.count():
            locator.first.fill(protocol_number)
            page.keyboard.press("Enter")
            page.wait_for_timeout(3000)
            break

    protocol_locator = page.locator(f"text={protocol_number}")
    if protocol_locator.count():
        protocol_locator.first.click()
        page.wait_for_timeout(3000)
        return True
    return False


def _extract_complaint_from_page(
    page: Page,
    protocol_number: str,
    *,
    consumer_name_hint: str | None,
    consumer_cpf_hint: str | None,
    complaint_date_hint: date | None,
    cause_hint: str | None,
) -> ProconComplaint:
    lines = [line.strip() for line in page.inner_text("body").splitlines() if line.strip()]

    def labeled_value(label: str) -> str:
        target = label.casefold()
        for index, line in enumerate(lines):
            if line.casefold() == target and index + 1 < len(lines):
                return lines[index + 1].strip()
        return ""

    consumer_name = labeled_value("Nome") or consumer_name_hint or ""
    consumer_cpf = _normalize_cpf(labeled_value("CPF") or consumer_cpf_hint or "")
    cause = (
        labeled_value("Descrição")
        or labeled_value("Reclamação")
        or cause_hint
        or ""
    )

    return ProconComplaint(
        access_code=protocol_number,
        consumer_name=consumer_name,
        consumer_cpf=consumer_cpf,
        cip_fa_number=protocol_number,
        complaint_date=_parse_brazilian_date(labeled_value("Data")) or complaint_date_hint,
        response_deadline=_parse_brazilian_date(labeled_value("Prazo")),
        cause=cause,
        state=UBERLANDIA_STATE_LABEL,
        portal_url=page.url,
    )


def _download_pdf_if_available(page: Page, download_dir: Path, protocol_number: str) -> str | None:
    download_dir.mkdir(parents=True, exist_ok=True)
    for label in ("Imprimir", "PDF", "Baixar", "Download", "Documento"):
        button = page.locator("button", has_text=label)
        link = page.locator("a", has_text=label)
        target = button if button.count() else link
        if not target.count():
            continue
        try:
            with page.expect_download(timeout=DEFAULT_TIMEOUT_MS) as download_info:
                target.first.click()
            download = download_info.value
            safe_protocol = protocol_number.replace(".", "-")
            target_path = download_dir / f"uberlandia-{safe_protocol}.pdf"
            download.save_as(target_path)
            return str(target_path)
        except PlaywrightTimeoutError:
            continue
    return None


def fetch_uberlandia_complaint(options: UberlandiaPortalOptions) -> ProconComplaint:
    """Login no Fale Procon Uberlândia e abre o processo pelo número."""
    options.download_dir.mkdir(parents=True, exist_ok=True)
    portal_url = options.credentials.portal_url
    if not portal_url:
        raise UberlandiaPortalError("URL do portal Uberlândia não configurada.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=options.headless)
        page = browser.new_page()
        try:
            page.goto(portal_url, wait_until=PAGE_LOAD_WAIT_UNTIL, timeout=DEFAULT_TIMEOUT_MS)
            page.wait_for_timeout(3000)
            _fill_login_fields(
                page,
                login=options.credentials.login,
                password=options.credentials.password,
            )
            _submit_login(page)
            if not _open_protocol(page, options.protocol_number):
                raise UberlandiaPortalError(
                    f"Processo {options.protocol_number} não encontrado no portal Uberlândia.",
                )
            complaint = _extract_complaint_from_page(
                page,
                options.protocol_number,
                consumer_name_hint=options.consumer_name_hint,
                consumer_cpf_hint=options.consumer_cpf_hint,
                complaint_date_hint=options.complaint_date_hint,
                cause_hint=options.cause_hint,
            )
            pdf_path = _download_pdf_if_available(
                page,
                options.download_dir,
                options.protocol_number,
            )
            if pdf_path:
                return ProconComplaint(
                    access_code=complaint.access_code,
                    consumer_name=complaint.consumer_name,
                    consumer_cpf=complaint.consumer_cpf,
                    cip_fa_number=complaint.cip_fa_number,
                    complaint_date=complaint.complaint_date,
                    response_deadline=complaint.response_deadline,
                    cause=complaint.cause,
                    state=complaint.state,
                    portal_url=complaint.portal_url,
                    pdf_path=pdf_path,
                )
            return complaint
        except PlaywrightTimeoutError as exc:
            raise UberlandiaPortalError(
                "Portal Uberlândia não respondeu a tempo durante o acesso.",
            ) from exc
        finally:
            browser.close()
