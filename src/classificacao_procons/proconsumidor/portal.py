"""Cliente do portal Proconsumidor via Playwright."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from classificacao_procons.credentials.mapping import PROCONSUMIDOR_SUPPLIER_LABELS
from classificacao_procons.credentials.models import PortalCredentials
from classificacao_procons.models import ProconComplaint

DEFAULT_TIMEOUT_MS: Final = 90_000
PAGE_LOAD_WAIT_UNTIL: Final = "domcontentloaded"
DEFAULT_USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class ProconsumidorPortalError(RuntimeError):
    """Erro ao acessar ou extrair dados do Proconsumidor."""


@dataclass(frozen=True)
class ProconsumidorPortalOptions:
    credentials: PortalCredentials
    complaint_number: str
    download_dir: Path
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


def _click_gestor_empresa_access(page: Page) -> None:
    for label in ("Acesso Gestor/Empresa", "Gestor/Empresa", "Gestor", "Empresa"):
        locator = page.locator("mat-radio-button", has_text=label)
        if locator.count():
            locator.first.click()
            return
    raise ProconsumidorPortalError("Opção Acesso Gestor/Empresa não encontrada no login.")


def _fill_login_fields(page: Page, *, login: str, password: str) -> None:
    login_filled = False
    for placeholder in ("CPF", "Login", "Usuário", "Usuario"):
        locator = page.get_by_placeholder(placeholder)
        if locator.count():
            locator.first.fill(login)
            login_filled = True
            break
    if not login_filled:
        text_inputs = page.locator("input:not([type='password'])")
        if text_inputs.count():
            text_inputs.first.fill(login)
        else:
            raise ProconsumidorPortalError("Campo de login não encontrado no Proconsumidor.")

    password_filled = False
    for placeholder in ("Senha", "Password"):
        locator = page.get_by_placeholder(placeholder)
        if locator.count():
            locator.first.fill(password)
            password_filled = True
            break
    if not password_filled:
        password_input = page.locator("input[type='password']")
        if password_input.count():
            password_input.first.fill(password)
        else:
            raise ProconsumidorPortalError("Campo de senha não encontrado no Proconsumidor.")


def _confirm_supplier_modal(page: Page) -> None:
    for label in ("Confirmar", "Acessar", "Entrar", "Selecionar"):
        button = page.locator("button", has_text=label)
        if button.count():
            button.first.click()
            page.wait_for_timeout(2000)
            return


def _select_supplier(page: Page, supplier_label: str) -> bool:
    if not page.locator("text=Selecionar Fornecedor").count():
        return True

    select_trigger = page.locator("mat-select").first
    if not select_trigger.count():
        return False

    select_trigger.click()
    page.wait_for_timeout(1000)
    option = page.locator("mat-option", has_text=supplier_label)
    if not option.count():
        page.keyboard.press("Escape")
        return False
    option.first.click()
    _confirm_supplier_modal(page)
    return True


def _create_browser_context(playwright: Any, *, headless: bool) -> tuple[Any, Any]:
    browser = playwright.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        user_agent=DEFAULT_USER_AGENT,
        viewport={"width": 1920, "height": 1080},
        extra_http_headers={
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    return browser, context


def _assert_portal_accessible(page: Page, *, portal_url: str) -> None:
    response = page.goto(portal_url, wait_until=PAGE_LOAD_WAIT_UNTIL, timeout=DEFAULT_TIMEOUT_MS)
    page.wait_for_timeout(3000)

    if response is not None and response.status == 403:
        raise ProconsumidorPortalError(
            "Portal Proconsumidor bloqueou o acesso (403). "
            "Execute em máquina local no Brasil (scripts/run-proconsumidor-process.sh).",
        )

    body_text = page.inner_text("body")
    if "403" in body_text and "Forbidden" in body_text:
        raise ProconsumidorPortalError(
            "Portal Proconsumidor bloqueou o acesso (403). "
            "Execute em máquina local no Brasil (scripts/run-proconsumidor-process.sh).",
        )


def _login(page: Page, credentials: PortalCredentials) -> None:
    portal_url = credentials.portal_url or "https://proconsumidor.mj.gov.br/#/login"
    _assert_portal_accessible(page, portal_url=portal_url)

    _click_gestor_empresa_access(page)
    _fill_login_fields(page, login=credentials.login, password=credentials.password)
    page.locator("button", has_text="Entrar").click()
    page.wait_for_timeout(5000)


def _open_complaint_with_suppliers(
    page: Page,
    *,
    credentials: PortalCredentials,
    complaint_number: str,
) -> bool:
    _login(page, credentials)

    for supplier_label in PROCONSUMIDOR_SUPPLIER_LABELS:
        if page.locator("text=Selecionar Fornecedor").count():
            if not _select_supplier(page, supplier_label):
                continue
        if _navigate_to_complaint(page, complaint_number):
            return True
        if page.locator("text=Selecionar Fornecedor").count():
            _login(page, credentials)

    return False


def _navigate_to_complaint(page: Page, complaint_number: str) -> bool:
    for placeholder in ("Número", "Numero", "Reclamação", "Reclamacao", "Protocolo", "Pesquisar"):
        locator = page.get_by_placeholder(placeholder)
        if locator.count():
            locator.first.fill(complaint_number)
            page.keyboard.press("Enter")
            page.wait_for_timeout(3000)
            break

    complaint_locator = page.locator(f"text={complaint_number}")
    if complaint_locator.count():
        complaint_locator.first.click()
        page.wait_for_timeout(3000)
        return True
    return False


def _extract_complaint_from_page(page: Page, complaint_number: str) -> ProconComplaint:
    lines = [line.strip() for line in page.inner_text("body").splitlines() if line.strip()]

    def labeled_value(label: str) -> str:
        target = label.casefold()
        for index, line in enumerate(lines):
            if line.casefold() == target and index + 1 < len(lines):
                return lines[index + 1].strip()
        return ""

    consumer_name = labeled_value("Nome") or labeled_value("Nome completo")
    consumer_cpf = _normalize_cpf(labeled_value("CPF"))
    cause = labeled_value("Assunto") or labeled_value("Descrição") or labeled_value("Descricao")

    return ProconComplaint(
        access_code=complaint_number,
        consumer_name=consumer_name,
        consumer_cpf=consumer_cpf,
        cip_fa_number=complaint_number,
        complaint_date=_parse_brazilian_date(labeled_value("Data de abertura")),
        response_deadline=_parse_brazilian_date(labeled_value("Prazo")),
        cause=cause,
        state="",
        portal_url=page.url,
    )


def _download_pdf_if_available(page: Page, download_dir: Path, complaint_number: str) -> str | None:
    download_dir.mkdir(parents=True, exist_ok=True)
    for label in ("Baixar", "Download", "PDF", "Imprimir"):
        button = page.locator("button", has_text=label)
        if not button.count():
            continue
        try:
            with page.expect_download(timeout=DEFAULT_TIMEOUT_MS) as download_info:
                button.first.click()
            download = download_info.value
            safe_number = complaint_number.replace("/", "-")
            target = download_dir / f"proconsumidor-{safe_number}.pdf"
            download.save_as(target)
            return str(target)
        except PlaywrightTimeoutError:
            continue
    return None


def fetch_proconsumidor_complaint(options: ProconsumidorPortalOptions) -> ProconComplaint:
    """Login no Proconsumidor, seleciona fornecedor e abre a reclamação."""
    options.download_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser, context = _create_browser_context(playwright, headless=options.headless)
        page = context.new_page()
        try:
            if not _open_complaint_with_suppliers(
                page,
                credentials=options.credentials,
                complaint_number=options.complaint_number,
            ):
                raise ProconsumidorPortalError(
                    f"Reclamação {options.complaint_number} não encontrada no Proconsumidor.",
                )
            complaint = _extract_complaint_from_page(page, options.complaint_number)
            pdf_path = _download_pdf_if_available(
                page,
                options.download_dir,
                options.complaint_number,
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
            raise ProconsumidorPortalError(
                "Portal Proconsumidor não respondeu a tempo durante o acesso.",
            ) from exc
        finally:
            context.close()
            browser.close()
