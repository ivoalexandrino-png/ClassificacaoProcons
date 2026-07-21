"""Consulta autenticada ao e-SAJ (TJSP e outros TJs que usam o SAJ).

Faz login com CPF/senha do quadro Acessos e lê a movimentação do processo,
inclusive em casos com visualização restrita a advogados habilitados (segredo
de justiça). Não resolve captcha nem 2FA: se o portal exigir, o cliente
levanta ``PortalRequiresInteraction`` e o fluxo cai para DataJud.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from classificacao_procons.juridico.acessos import PortalCredential
from classificacao_procons.juridico.cnj import process_number_digits

ESAJ_LOGIN_URL = "https://esaj.tjsp.jus.br/sajcas/login"
ESAJ_CPOPG_URL = "https://esaj.tjsp.jus.br/cpopg/open.do"
ESAJ_CPOSG_URL = "https://esaj.tjsp.jus.br/cposg/open.do"
_DEFAULT_TIMEOUT_MS = 45000
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class PortalError(RuntimeError):
    """Falha ao consultar o portal do tribunal."""


class PortalRequiresInteraction(PortalError):
    """Portal exigiu captcha/2FA/certificado — precisa de humano."""


@dataclass(frozen=True)
class ProcessContent:
    process_number: str
    source: str
    classe: str | None = None
    assunto: str | None = None
    situacao: str | None = None
    movements: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        header = " — ".join(
            part for part in (self.classe, self.assunto, self.situacao) if part
        )
        lines = [f"Teor do processo {self.process_number} (fonte: {self.source})"]
        if header:
            lines.append(header)
        if self.movements:
            lines.append("Movimentações:")
            lines.extend(f"- {movement}" for movement in self.movements)
        return "\n".join(lines)


def _digits_to_unified(digits: str) -> tuple[str, str]:
    """Divide os 20 dígitos em (NNNNNNN-DD.AAAA.J.TR, OOOO) para o e-SAJ."""
    return f"{digits[:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13]}.{digits[14:16]}", digits[16:]


def _login(page, credential: PortalCredential) -> None:
    page.goto(ESAJ_LOGIN_URL, timeout=_DEFAULT_TIMEOUT_MS, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if "recaptcha" in page.content().lower():
        raise PortalRequiresInteraction("e-SAJ exigiu captcha no login.")
    try:
        page.fill("#usernameForm", credential.login)
        page.fill("#passwordForm", credential.password)
        page.click("#pbEntrar")
    except PlaywrightTimeoutError as exc:
        raise PortalError(f"Formulário de login do e-SAJ mudou: {exc}") from exc
    page.wait_for_timeout(3000)

    content = page.content().lower()
    if "senha inv" in content or "usuário ou senha" in content or "usuario ou senha" in content:
        raise PortalError("e-SAJ recusou as credenciais (login/senha).")
    if "token" in content and "autenticacao" in content:
        raise PortalRequiresInteraction("e-SAJ exigiu 2FA/token.")


def _extract_content(page, process_number: str, source: str) -> ProcessContent:
    def _text(selector: str) -> str | None:
        element = page.query_selector(selector)
        if element is None:
            return None
        value = " ".join(element.inner_text().split()).strip()
        return value or None

    rows = page.query_selector_all(
        "#tabelaTodasMovimentacoes tr, #tabelaUltimasMovimentacoes tr",
    )
    movements = []
    for row in rows:
        text = " ".join(row.inner_text().split())
        if text:
            movements.append(text[:300])

    return ProcessContent(
        process_number=process_number,
        source=source,
        classe=_text("#classeProcesso"),
        assunto=_text("#assuntoProcesso"),
        situacao=_text("#situacaoProcesso") or _text("#situacaoProcessoProcSituacao"),
        movements=movements[:20],
    )


def _consult_instance(page, *, base_url: str, process_number: str, source: str) -> ProcessContent:
    digits = process_number_digits(process_number)
    numero_unificado, foro = _digits_to_unified(digits)

    page.goto(base_url, timeout=_DEFAULT_TIMEOUT_MS, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    page.fill("#numeroDigitoAnoUnificado", numero_unificado)
    page.fill("#foroNumeroUnificado", foro)
    page.click("#pbConsultar")
    page.wait_for_timeout(3500)

    content = page.content().lower()
    if "recaptcha" in content or "g-recaptcha" in content:
        raise PortalRequiresInteraction("e-SAJ exigiu captcha na consulta.")
    if "senha do processo" in content or "necessário identificar-se" in content:
        raise PortalRequiresInteraction(
            "Processo em segredo de justiça: exige advogado habilitado nos autos.",
        )
    return _extract_content(page, process_number, source)


def fetch_process_content(
    process_number: str,
    *,
    credential: PortalCredential,
    headless: bool = True,
) -> ProcessContent:
    """Loga no e-SAJ e retorna a movimentação do processo (1º ou 2º grau)."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            page = browser.new_page(user_agent=_USER_AGENT)
            page.set_default_timeout(_DEFAULT_TIMEOUT_MS)
            _login(page, credential)

            last_error: PortalError | None = None
            for base_url, source in (
                (ESAJ_CPOPG_URL, "e-SAJ 1º grau"),
                (ESAJ_CPOSG_URL, "e-SAJ 2º grau"),
            ):
                try:
                    content = _consult_instance(
                        page,
                        base_url=base_url,
                        process_number=process_number,
                        source=source,
                    )
                except PortalRequiresInteraction:
                    raise
                except PortalError as exc:
                    last_error = exc
                    continue
                if content.movements or content.classe:
                    return content
            if last_error:
                raise last_error
            raise PortalError("Processo não encontrado no e-SAJ (1º/2º grau).")
        finally:
            browser.close()
