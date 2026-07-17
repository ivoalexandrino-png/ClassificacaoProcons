"""Cliente do portal Procon-SP via Playwright."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Final

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from classificacao_procons.models import ProconComplaint

PORTAL_LOGIN_URL: Final = "https://fornecedor2.procon.sp.gov.br/login"
DEFAULT_TIMEOUT_MS: Final = 90_000
PAGE_LOAD_WAIT_UNTIL: Final = "domcontentloaded"


class ProconPortalError(RuntimeError):
    """Erro ao acessar ou extrair dados do portal Procon-SP."""


@dataclass(frozen=True)
class PortalFetchOptions:
    access_code: str
    download_dir: Path
    headless: bool = True


def _parse_brazilian_date(value: str) -> date | None:
    value = value.strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_cpf(value: str) -> str:
    return re.sub(r"\D", "", value)


def _labeled_value(lines: list[str], label: str) -> str:
    target = label.casefold()
    for index, line in enumerate(lines):
        if line.casefold() == target and index + 1 < len(lines):
            return lines[index + 1].strip()
    return ""


def _build_cause_text(classification: str, complaint_details: str) -> str:
    """Combina classificação Procon e detalhes para mapeamento no Monday."""
    parts = [part.strip() for part in (classification, complaint_details) if part.strip()]
    if not parts:
        return ""
    return " ".join(parts)


def _complaint_details(lines: list[str]) -> str:
    start = -1
    for index, line in enumerate(lines):
        if line.casefold() == "reclamação" and index + 2 < len(lines):
            if lines[index + 1].casefold() == "detalhes":
                start = index + 2
                break
    if start < 0:
        return ""

    collected: list[str] = []
    stop_labels = {
        "pedido",
        "anexos",
        "documentos da compra/contratação",
        "prodesp - tecnologia da informação",
    }
    for line in lines[start:]:
        if line.casefold() in stop_labels:
            break
        collected.append(line)
    return " ".join(collected).strip()


def _goto_portal_login(page: Page) -> None:
    """Abre o login do portal com retentativas (networkidle falha em SPAs)."""
    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            page.goto(
                PORTAL_LOGIN_URL,
                wait_until=PAGE_LOAD_WAIT_UNTIL,
                timeout=DEFAULT_TIMEOUT_MS,
            )
            page.locator("mat-radio-button", has_text="Reclamação").wait_for(
                state="visible",
                timeout=DEFAULT_TIMEOUT_MS,
            )
            return
        except PlaywrightTimeoutError as exc:
            last_error = exc

    raise ProconPortalError(
        "Portal Procon-SP não carregou a tempo. Tente novamente em alguns minutos.",
    ) from last_error


def _open_complaint_with_code(page: Page, access_code: str) -> None:
    _goto_portal_login(page)
    page.locator("mat-radio-button", has_text="Reclamação").click()
    page.locator("button", has_text="Continuar").click()
    page.get_by_placeholder("Código da reclamação").fill(access_code)
    page.locator("button", has_text="Validar código de acesso").click()
    page.wait_for_timeout(3000)

    body_text = page.inner_text("body")
    if "não é válido" in body_text.lower():
        raise ProconPortalError(f"Código de acesso inválido: {access_code}")

    if "/m/atendimentos" not in page.url:
        raise ProconPortalError("Não foi possível abrir a página da reclamação.")


def _extract_complaint_from_page(page: Page, access_code: str) -> ProconComplaint:
    page.wait_for_timeout(2000)
    lines = [line.strip() for line in page.inner_text("body").splitlines() if line.strip()]

    consumer_name = _labeled_value(lines, "Nome completo")
    consumer_cpf = _normalize_cpf(_labeled_value(lines, "CPF"))
    cip_fa_number = _labeled_value(lines, "Protocolo")
    classification = _labeled_value(lines, "Classificação")
    complaint_details = _complaint_details(lines)
    cause = _build_cause_text(classification, complaint_details)

    return ProconComplaint(
        access_code=access_code,
        consumer_name=consumer_name,
        consumer_cpf=consumer_cpf,
        cip_fa_number=cip_fa_number,
        complaint_date=_parse_brazilian_date(_labeled_value(lines, "Data da solicitação")),
        response_deadline=_parse_brazilian_date(_labeled_value(lines, "Prazo")),
        cause=cause,
        portal_url=page.url,
    )


def _download_pdf_from_documents_tab(
    page: Page,
    download_dir: Path,
    access_code: str,
) -> str | None:
    page.get_by_role("tab", name="Documentos Procon").click()
    page.wait_for_timeout(2000)

    document_row = page.locator("text=ATENDIMENTO CIP")
    if not document_row.count():
        return None

    download_dir.mkdir(parents=True, exist_ok=True)
    try:
        with page.expect_download(timeout=DEFAULT_TIMEOUT_MS) as download_info:
            document_row.first.click()
        download = download_info.value
        target = download_dir / f"procon-{access_code.replace('/', '-')}.pdf"
        download.save_as(target)
        return str(target)
    except PlaywrightTimeoutError:
        return None


def fetch_complaint(options: PortalFetchOptions) -> ProconComplaint:
    """Acessa o portal com o código e extrai dados da reclamação."""
    options.download_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=options.headless)
        page = browser.new_page()
        try:
            try:
                _open_complaint_with_code(page, options.access_code)
                complaint = _extract_complaint_from_page(page, options.access_code)
                pdf_path = _download_pdf_from_documents_tab(
                    page,
                    options.download_dir,
                    options.access_code,
                )
            except PlaywrightTimeoutError as exc:
                raise ProconPortalError(
                    "Portal Procon-SP não respondeu a tempo durante o acesso.",
                ) from exc
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
        finally:
            browser.close()
