"""Portal Procon-SP com login gov.br / procurador (sessão persistida)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from classificacao_procons.portal.client import PORTAL_LOGIN_URL, ProconPortalError

PA_LIST_URL_FRAGMENT = "/m/atendimentos"


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
