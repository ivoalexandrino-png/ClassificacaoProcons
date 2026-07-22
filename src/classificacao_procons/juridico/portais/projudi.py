"""Consulta autenticada ao Projudi (TJPR, TJBA, TJAM e outros).

O Projudi não abre consulta pública (retorna "acesso negado"); o login é por
usuário/senha (Keycloak, sem captcha), com credenciais do quadro Acessos. Sem
credencial do tribunal, o cliente avisa e o fluxo cai para o DataJud.
"""

from __future__ import annotations

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from classificacao_procons.juridico.acessos import PortalCredential
from classificacao_procons.juridico.cnj import process_number_digits
from classificacao_procons.juridico.portais.base import (
    _DEFAULT_TIMEOUT_MS,
    _USER_AGENT,
    PortalError,
    PortalRequiresInteraction,
    ProcessContent,
    dedupe_movements,
)

# Domínio do Projudi por UF do tribunal (sigla TJ<UF>).
_PROJUDI_HOSTS: dict[str, str] = {
    "TJPR": "https://projudi.tjpr.jus.br/projudi/",
    "TJBA": "https://projudi.tjba.jus.br/projudi/",
    "TJAM": "https://projudi.tjam.jus.br/projudi/",
    "TJSC": "https://projudi.tjsc.jus.br/projudi/",
}


def projudi_host(tribunal_acronym: str) -> str | None:
    return _PROJUDI_HOSTS.get(tribunal_acronym.upper())


# Captchas conhecidos na tela de login do Projudi (variam por tribunal):
# reCAPTCHA (TJ genérico) e o drag-puzzle Turing/Tencent (TJBA).
_CAPTCHA_MARKERS = ("g-recaptcha", "recaptcha/api", "turing.captcha", "gtimg.com", "drag_ele")


def _has_login_captcha(page) -> bool:
    content = page.content().lower()
    if any(marker in content for marker in _CAPTCHA_MARKERS):
        return True
    return any(
        any(marker in (frame.url or "").lower() for marker in _CAPTCHA_MARKERS)
        for frame in page.frames
    )


def _login(page, *, host: str, credential: PortalCredential) -> None:
    page.goto(host, timeout=_DEFAULT_TIMEOUT_MS, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    if _has_login_captcha(page):
        raise PortalRequiresInteraction(
            "Projudi exigiu captcha no login (varia por tribunal); "
            "andamentos seguem pelo DataJud.",
        )

    user = page.query_selector("#username, input[name=username], #login")
    password = page.query_selector("#password, input[name=password], #senha")
    if user is None or password is None:
        raise PortalError("Formulário de login do Projudi não encontrado.")
    try:
        user.fill(credential.login)
        password.fill(credential.password)
        button = (
            page.query_selector("#kc-login")
            or page.query_selector("input[type=submit]")
            or page.query_selector("button[type=submit]")
        )
        if button is None:
            raise PortalError("Botão de login do Projudi não encontrado.")
        button.click()
        page.wait_for_timeout(3500)
    except PlaywrightTimeoutError as exc:
        raise PortalError(f"Login do Projudi não respondeu: {exc}") from exc

    content = page.content().lower()
    refused = "inv" in content or "incorret" in content or "credenciais" in content
    if "senha" in content and refused:
        raise PortalError("Projudi recusou as credenciais (login/senha).")


def _extract(page, process_number: str, tribunal_acronym: str) -> ProcessContent:
    rows = [
        row.inner_text()
        for row in page.query_selector_all(
            "#tabelaMovimentacoes tr, table.resultTable tr, .movimentacao",
        )
    ]
    movements = dedupe_movements(rows)
    return ProcessContent(
        process_number=process_number,
        source=f"Projudi {tribunal_acronym}",
        movements=movements,
    )


def fetch_process_content(
    process_number: str,
    *,
    tribunal_acronym: str,
    credential: PortalCredential,
    headless: bool = True,
) -> ProcessContent:
    """Loga no Projudi do tribunal e lê a movimentação do processo."""
    host = projudi_host(tribunal_acronym)
    if host is None:
        raise PortalError(f"Projudi de {tribunal_acronym} não mapeado.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            page = browser.new_context(user_agent=_USER_AGENT).new_page()
            page.set_default_timeout(_DEFAULT_TIMEOUT_MS)
            _login(page, host=host, credential=credential)

            search_url = (
                f"{host}processo/consultaPublica.do?actionType=pesquisar"
                f"&numeroProcesso={process_number_digits(process_number)}"
            )
            try:
                page.goto(search_url, timeout=_DEFAULT_TIMEOUT_MS, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
            except PlaywrightTimeoutError as exc:
                raise PortalError(f"Projudi não respondeu à consulta: {exc}") from exc

            content = page.content().lower()
            if "acesso negado" in content or "não possui permissão" in content:
                raise PortalRequiresInteraction(
                    "Projudi negou acesso ao processo (habilitação/segredo).",
                )
            result = _extract(page, process_number, tribunal_acronym)
            if not result.movements:
                raise PortalError("Projudi não retornou movimentações.")
            return result
        finally:
            browser.close()
