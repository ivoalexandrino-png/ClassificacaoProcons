"""Consulta processual no PJe (Justiça do Trabalho e outros tribunais).

A consulta pública do PJe é protegida por captcha (Resolução 139/2014 do CSJT):
não dá para automatizar sem resolução humana. Este cliente monta a consulta,
detecta o captcha e devolve ``PortalRequiresInteraction`` — assim o fluxo cai
para o DataJud e, se um tribunal específico dispensar o captcha, a leitura
passa a funcionar sem mudança de código.
"""

from __future__ import annotations

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from classificacao_procons.juridico.cnj import process_number_digits
from classificacao_procons.juridico.portais.base import (
    _DEFAULT_TIMEOUT_MS,
    _USER_AGENT,
    PortalError,
    PortalRequiresInteraction,
    ProcessContent,
    dedupe_movements,
)

# Base da consulta pública por tribunal do trabalho (TRT<n>).
PJE_CONSULTA_URL = "https://pje.trt{regional}.jus.br/consultaprocessual/"


def _regional_from_alias(alias: str) -> str | None:
    """Extrai o número do TRT do alias DataJud (ex.: 'trt2' -> '2')."""
    if alias and alias.lower().startswith("trt"):
        digits = alias[3:]
        return digits or None
    return None


def _has_captcha(page) -> bool:
    content = page.content().lower()
    if "resolução n" in content and "139/2014" in content:
        return True
    return bool(
        page.query_selector("#captcha, img[src*=captcha], input[name*=captcha]")
        or "digite os caracteres exibidos na imagem" in content,
    )


def fetch_process_content_public(
    process_number: str,
    *,
    alias: str,
    headless: bool = True,
) -> ProcessContent:
    """Consulta pública do PJe. Levanta PortalRequiresInteraction se houver captcha."""
    regional = _regional_from_alias(alias)
    if regional is None:
        raise PortalError(f"Alias PJe não suportado: {alias}.")

    url = PJE_CONSULTA_URL.format(regional=regional)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            page = browser.new_context(user_agent=_USER_AGENT).new_page()
            page.set_default_timeout(_DEFAULT_TIMEOUT_MS)
            try:
                page.goto(url, timeout=_DEFAULT_TIMEOUT_MS, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                campo = page.query_selector("#nrProcessoInput")
                if campo is None:
                    raise PortalError("Formulário de consulta do PJe não encontrado.")
                campo.click()
                page.keyboard.type(process_number_digits(process_number), delay=30)
                page.keyboard.press("Enter")
                page.wait_for_timeout(4000)
            except PlaywrightTimeoutError as exc:
                raise PortalError(f"PJe não respondeu a tempo: {exc}") from exc

            if _has_captcha(page):
                raise PortalRequiresInteraction(
                    "PJe exige captcha na consulta pública (Res. 139/2014 CSJT); "
                    "andamentos seguem pelo DataJud.",
                )

            rows = [
                row.inner_text()
                for row in page.query_selector_all(
                    "table.rich-table tbody tr, .movimentacao, .timeline-item",
                )
            ]
            movements = dedupe_movements(rows)
            if not movements:
                raise PortalError("PJe não retornou movimentações públicas.")
            return ProcessContent(
                process_number=process_number,
                source=f"PJe TRT{regional} (público)",
                movements=movements,
            )
        finally:
            browser.close()
