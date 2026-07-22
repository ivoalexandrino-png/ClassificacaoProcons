"""Consulta autenticada ao e-SAJ (TJSP e outros TJs que usam o SAJ).

Faz login com CPF/senha do quadro Acessos e lê a movimentação do processo,
inclusive em casos com visualização restrita a advogados habilitados (segredo
de justiça). Não resolve captcha nem 2FA: se o portal exigir, o cliente
levanta ``PortalRequiresInteraction`` e o fluxo cai para DataJud.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from classificacao_procons.juridico.acessos import PortalCredential
from classificacao_procons.juridico.cnj import process_number_digits

ESAJ_LOGIN_URL = "https://esaj.tjsp.jus.br/sajcas/login"
ESAJ_CPOPG_URL = "https://esaj.tjsp.jus.br/cpopg/open.do"
ESAJ_CPOSG_URL = "https://esaj.tjsp.jus.br/cposg/open.do"
ESAJ_HOME_URL = "https://esaj.tjsp.jus.br/esaj/portal.do?servico=740000"
_DEFAULT_TIMEOUT_MS = 45000
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Sessão autenticada persistida (cookies) para o 2FA ser pedido só de vez em
# quando, não a cada consulta.
DEFAULT_SESSION_PATH = "credentials/esaj-session.json"

# Provedor do código 2FA: recebe o e-mail/login e devolve o código enviado.
TokenProvider = Callable[[str], str | None]


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
    """Divide os 20 dígitos para os dois campos do e-SAJ.

    O campo ``numeroDigitoAnoUnificado`` recebe só ``NNNNNNN-DD.AAAA`` (o
    ``.J.TR`` fica fixo na tela); ``foroNumeroUnificado`` recebe os 4 dígitos
    finais (o foro/origem).
    """
    return f"{digits[:7]}-{digits[7:9]}.{digits[9:13]}", digits[16:]


def _is_logged_in(page) -> bool:
    page.goto(ESAJ_HOME_URL, timeout=_DEFAULT_TIMEOUT_MS, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    body = page.inner_text("body").lower()
    return "sair" in body or "caixa postal" in body


def _submit_token(page, code: str) -> None:
    """Preenche o código 2FA enviado por e-mail e confirma."""
    field = (
        page.query_selector("#token")
        or page.query_selector("input[name=token]")
        or page.query_selector("input[type=text]:visible")
    )
    if field is None:
        raise PortalRequiresInteraction("Campo do código 2FA não encontrado no e-SAJ.")
    field.fill(code)
    button = page.query_selector("#btnEnviarToken") or page.query_selector("#btnOk")
    if button:
        button.click()
    else:
        page.keyboard.press("Enter")
    page.wait_for_timeout(3000)


def _requires_token(page) -> bool:
    content = page.content().lower()
    if page.query_selector("#btnEnviarToken") or page.query_selector("#btnReceberToken"):
        return True
    return "codigo" in content and "email" in content and "token" in content


def _login(
    page,
    credential: PortalCredential,
    *,
    token_provider: TokenProvider | None = None,
) -> None:
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

    if _requires_token(page):
        if token_provider is None:
            raise PortalRequiresInteraction(
                "e-SAJ enviou um código 2FA ao e-mail cadastrado; nenhum provedor "
                "de código configurado. Rode com --headed ou configure o token.",
            )
        code = token_provider(credential.login)
        if not code:
            raise PortalRequiresInteraction(
                "Código 2FA do e-SAJ não recebido/localizado no e-mail a tempo.",
            )
        _submit_token(page, code)
        if _requires_token(page):
            raise PortalRequiresInteraction("Código 2FA do e-SAJ recusado ou expirado.")


def _extract_content(page, process_number: str, source: str) -> ProcessContent:
    def _text(selector: str) -> str | None:
        element = page.query_selector(selector)
        if element is None:
            return None
        value = " ".join(element.inner_text().split()).strip()
        return value or None

    # "Todas" e "Últimas" repetem linhas; preferir a tabela completa e dedupe.
    rows = page.query_selector_all("#tabelaTodasMovimentacoes tr")
    if not rows:
        rows = page.query_selector_all("#tabelaUltimasMovimentacoes tr")
    movements: list[str] = []
    seen: set[str] = set()
    for row in rows:
        text = " ".join(row.inner_text().split())[:300]
        if text and text not in seen:
            seen.add(text)
            movements.append(text)

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

    try:
        page.goto(base_url, timeout=_DEFAULT_TIMEOUT_MS, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        page.fill("#numeroDigitoAnoUnificado", numero_unificado)
        page.fill("#foroNumeroUnificado", foro)
        consultar = page.query_selector("#botaoConsultarProcessos") or page.query_selector(
            "#pbConsultar",
        )
        if consultar is None:
            raise PortalError("Botão de consulta do e-SAJ não encontrado.")
        try:
            with page.expect_navigation(timeout=_DEFAULT_TIMEOUT_MS):
                consultar.click()
        except PlaywrightTimeoutError:
            # algumas consultas resolvem sem troca de URL (resultado inline)
            page.wait_for_timeout(2000)
        page.wait_for_timeout(2000)
    except PlaywrightTimeoutError as exc:
        # e-SAJ lento/instável: não pode virar traceback — vira erro tratável.
        raise PortalError(f"e-SAJ não respondeu a tempo ({source}): {exc}") from exc

    content = page.content().lower()
    if "recaptcha" in content or "g-recaptcha" in content:
        raise PortalRequiresInteraction("e-SAJ exigiu captcha na consulta.")

    # A extração define o veredito: se veio classe/movimentação, é público.
    # "Identificar-se" aparece no cabeçalho de QUALQUER página e não indica
    # segredo por si só — o sinal real é a tela "SENHA DO PROCESSO" sem dados.
    result = _extract_content(page, process_number, source)
    if result.movements or result.classe:
        return result

    if "senha do processo" in content or "segredo de justi" in content:
        raise PortalRequiresInteraction(
            "Processo em segredo de justiça: exige advogado habilitado nos autos.",
        )
    raise PortalError("Processo não encontrado nesta instância do e-SAJ.")


def fetch_process_content_public(
    process_number: str,
    *,
    headless: bool = True,
) -> ProcessContent:
    """Consulta pública do e-SAJ, SEM login (cobre processos não sigilosos).

    É o caminho preferencial: não precisa de credencial nem 2FA. Levanta
    ``PortalRequiresInteraction`` quando o processo está em segredo de justiça
    (exige advogado habilitado) — aí o chamador tenta o modo autenticado.
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            page = browser.new_context(user_agent=_USER_AGENT).new_page()
            page.set_default_timeout(_DEFAULT_TIMEOUT_MS)
            last_error: PortalError | None = None
            for base_url, source in (
                (ESAJ_CPOPG_URL, "e-SAJ 1º grau (público)"),
                (ESAJ_CPOSG_URL, "e-SAJ 2º grau (público)"),
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


def fetch_process_content(
    process_number: str,
    *,
    credential: PortalCredential,
    headless: bool = True,
    token_provider: TokenProvider | None = None,
    session_path: str | None = DEFAULT_SESSION_PATH,
) -> ProcessContent:
    """Loga no e-SAJ e retorna a movimentação do processo (1º ou 2º grau).

    Reaproveita a sessão salva em ``session_path`` (cookies) para evitar 2FA a
    cada consulta; só faz login completo quando a sessão expirou.
    """
    storage_state = session_path if session_path and Path(session_path).exists() else None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            context = browser.new_context(user_agent=_USER_AGENT, storage_state=storage_state)
            page = context.new_page()
            page.set_default_timeout(_DEFAULT_TIMEOUT_MS)

            if not (storage_state and _is_logged_in(page)):
                _login(page, credential, token_provider=token_provider)
                if session_path:
                    Path(session_path).parent.mkdir(parents=True, exist_ok=True)
                    context.storage_state(path=session_path)
                    os.chmod(session_path, 0o600)

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
