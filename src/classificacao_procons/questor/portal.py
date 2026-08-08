"""Coleta do Questor via Playwright (login → certidões + caixa postal).

O layout do Questor varia por versão/implantação; por isso o login usa seletores
heurísticos (como em ``campinas/portal.py``) e a extração converte o texto das
tabelas em modelos com os helpers de ``parser.py``. Os seletores/rotas precisam
ser calibrados contra o ambiente real do cliente na primeira execução assistida.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from classificacao_procons.questor.models import (
    Certidao,
    MensagemCaixaPostal,
    QuestorSnapshot,
)
from classificacao_procons.questor.parser import (
    normalize_cnpj,
    normalize_situacao,
    parse_brazilian_date,
)

DEFAULT_TIMEOUT_MS: Final = 90_000
PAGE_LOAD_WAIT_UNTIL: Final = "domcontentloaded"

_DATE_RE = re.compile(r"\d{2}/\d{2}/\d{4}")


class QuestorPortalError(RuntimeError):
    """Erro ao acessar ou extrair dados do Questor."""


@dataclass(frozen=True)
class QuestorPortalOptions:
    portal_url: str
    login: str
    password: str
    empresa: str | None = None
    cnpj: str | None = None
    certidoes_url: str | None = None
    caixa_postal_url: str | None = None
    headless: bool = True


def _fill_login_fields(page: Page, *, login: str, password: str) -> None:
    login_filled = False
    for selector in (
        "input[name*='login' i]",
        "input[id*='login' i]",
        "input[name*='usuario' i]",
        "input[id*='usuario' i]",
        "input[name*='email' i]",
        "input[type='email']",
        "input[type='text']",
    ):
        locator = page.locator(selector)
        if locator.count():
            locator.first.fill(login)
            login_filled = True
            break
    if not login_filled:
        raise QuestorPortalError("Campo de login não encontrado no Questor.")

    password_input = page.locator("input[type='password']")
    if not password_input.count():
        raise QuestorPortalError("Campo de senha não encontrado no Questor.")
    password_input.first.fill(password)


def _submit_login(page: Page) -> None:
    for label in ("Entrar", "Acessar", "Login", "Conectar"):
        button = page.locator("button", has_text=label)
        if button.count():
            button.first.click()
            page.wait_for_timeout(4000)
            return
    submit = page.locator("input[type='submit']")
    if submit.count():
        submit.first.click()
        page.wait_for_timeout(4000)
        return
    raise QuestorPortalError("Botão de login não encontrado no Questor.")


def _page_lines(page: Page) -> list[str]:
    return [line.strip() for line in page.inner_text("body").splitlines() if line.strip()]


def parse_certidoes_lines(lines: list[str], *, cnpj: str | None = None) -> list[Certidao]:
    """Converte linhas de texto da tela de certidões em modelos.

    Heurística: cada linha com um rótulo de situação conhecido vira uma certidão;
    o órgão é o começo da linha e as datas encontradas viram emissão/validade.
    """
    certidoes: list[Certidao] = []
    for line in lines:
        situacao = normalize_situacao(line)
        if situacao == "desconhecida":
            continue
        dates = [parse_brazilian_date(match.group()) for match in _DATE_RE.finditer(line)]
        dates = [value for value in dates if value is not None]
        data_emissao = dates[0] if dates else None
        data_validade = dates[-1] if len(dates) > 1 else None
        orgao = _leading_label(line)
        # Ignora cabeçalhos/títulos: o rótulo do órgão não pode ser, ele mesmo,
        # uma situação (ex.: "Certidões negativas").
        if not orgao or normalize_situacao(orgao) != "desconhecida":
            continue
        certidoes.append(
            Certidao(
                orgao=orgao,
                situacao=situacao,
                cnpj=normalize_cnpj(cnpj),
                data_emissao=data_emissao,
                data_validade=data_validade,
                observacao=line,
            ),
        )
    return certidoes


def _leading_label(line: str) -> str:
    """Rótulo do órgão: texto antes da primeira data ou de dois espaços/tab."""
    cut = re.split(r"\s{2,}|\t|\d{2}/\d{2}/\d{4}", line, maxsplit=1)[0]
    return cut.strip(" :-\u00a0")


def _extract_certidoes(page: Page, *, cnpj: str | None) -> list[Certidao]:
    return parse_certidoes_lines(_page_lines(page), cnpj=cnpj)


def _extract_mensagens(page: Page) -> list[MensagemCaixaPostal]:
    mensagens: list[MensagemCaixaPostal] = []
    rows = page.locator("table tr")
    for index in range(rows.count()):
        row = rows.nth(index)
        text = row.inner_text().strip()
        if not text:
            continue
        folded = text.casefold()
        if "prazo" in folded and "assunto" in folded:
            continue  # cabeçalho
        dates = [parse_brazilian_date(match.group()) for match in _DATE_RE.finditer(text)]
        dates = [value for value in dates if value is not None]
        lida = "lida" in folded and "não lida" not in folded and "nao lida" not in folded
        mensagens.append(
            MensagemCaixaPostal(
                orgao=_leading_label(text) or "Caixa postal",
                assunto=text,
                data_postagem=dates[0] if dates else None,
                prazo_ciencia=dates[-1] if len(dates) > 1 else None,
                lida=lida,
            ),
        )
    return mensagens


def fetch_questor_snapshot(options: QuestorPortalOptions) -> QuestorSnapshot:
    """Login no Questor e coleta certidões + mensagens da caixa postal."""
    if not options.portal_url:
        raise QuestorPortalError("URL do Questor não configurada.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=options.headless)
        page = browser.new_page()
        try:
            page.goto(
                options.portal_url,
                wait_until=PAGE_LOAD_WAIT_UNTIL,
                timeout=DEFAULT_TIMEOUT_MS,
            )
            page.wait_for_timeout(3000)
            _fill_login_fields(page, login=options.login, password=options.password)
            _submit_login(page)

            if options.certidoes_url:
                page.goto(
                    options.certidoes_url,
                    wait_until=PAGE_LOAD_WAIT_UNTIL,
                    timeout=DEFAULT_TIMEOUT_MS,
                )
                page.wait_for_timeout(2000)
            certidoes = _extract_certidoes(page, cnpj=options.cnpj)

            if options.caixa_postal_url:
                page.goto(
                    options.caixa_postal_url,
                    wait_until=PAGE_LOAD_WAIT_UNTIL,
                    timeout=DEFAULT_TIMEOUT_MS,
                )
                page.wait_for_timeout(2000)
            mensagens = _extract_mensagens(page)

            return QuestorSnapshot(
                captured_at=datetime.now(UTC),
                empresa=options.empresa,
                cnpj=normalize_cnpj(options.cnpj),
                certidoes=tuple(certidoes),
                mensagens=tuple(mensagens),
            )
        except PlaywrightTimeoutError as exc:
            raise QuestorPortalError("Questor não respondeu a tempo durante o acesso.") from exc
        finally:
            browser.close()
