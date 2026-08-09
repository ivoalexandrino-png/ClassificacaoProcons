"""Coleta do Questor Zen: login web + endpoints JSON internos (CND e DTE).

Calibrado contra ``https://<conta>.zen.questor.com.br`` (login ``#Email``/
``#SenhaEntrar`` + consentimento de cookies), consumindo os endpoints DevExtreme
usados pelos grids:

- Certidões: ``POST /escritorio/cnd/certidaoempresa/listarcertidaoempresa``
- Caixa postal: ``POST /escritorio/dte/capturacaixapostal/listar``

Ambos aceitam ``skip/take/requireTotalCount`` e devolvem ``{data, totalCount}``.
Buscamos o dataset completo (take alto) e filtramos em Python — mais robusto que
raspar o DOM paginado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from typing import Any, Final
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from classificacao_procons.questor.models import (
    Certidao,
    MensagemCaixaPostal,
    QuestorSnapshot,
)
from classificacao_procons.questor.parser import (
    leitura_is_lida,
    normalize_cnpj,
    parse_brazilian_date,
    situacao_from_questor_code,
)

DEFAULT_TIMEOUT_MS: Final = 90_000
PAGE_LOAD_WAIT_UNTIL: Final = "domcontentloaded"
DEFAULT_TAKE: Final = 2000

CERTIDOES_ENDPOINT: Final = "escritorio/cnd/certidaoempresa/listarcertidaoempresa"
CAIXA_POSTAL_ENDPOINT: Final = "escritorio/dte/capturacaixapostal/listar"
NOTIFICATION_URL_TEMPLATE: Final = "https://www.dec.fazenda.sp.gov.br/DEC/UCLogin/login.aspx"


class QuestorPortalError(RuntimeError):
    """Erro ao acessar ou extrair dados do Questor."""


@dataclass(frozen=True)
class QuestorPortalOptions:
    portal_url: str
    login: str
    password: str
    empresa: str | None = None
    cnpj: str | None = None
    headless: bool = True
    take: int = DEFAULT_TAKE


def certidao_from_api_row(row: dict[str, Any]) -> Certidao:
    """Converte uma linha do endpoint de certidões em ``Certidao``."""
    tipo = (row.get("TipoCertidaoDescricao") or "").strip() or None
    categoria = (row.get("Categoria") or "").strip() or None
    orgao = tipo or categoria or "Certidão"
    return Certidao(
        orgao=orgao,
        situacao=situacao_from_questor_code(row.get("SituacaoCertidao")),
        tipo=categoria,
        cnpj=normalize_cnpj(row.get("EmpresaInscricaoFederal")),
        empresa=(row.get("EmpresaNome") or row.get("EmpresaRazaoSocial") or "").strip() or None,
        uf=(row.get("UF") or "").strip() or None,
        data_emissao=parse_brazilian_date(row.get("CertidaoDataEmissao")),
        data_validade=parse_brazilian_date(row.get("CertidaoDataVencimento")),
        observacao=(row.get("CertidaoProtocolo") or "").strip() or None,
    )


def mensagem_from_api_row(row: dict[str, Any]) -> MensagemCaixaPostal:
    """Converte uma linha do endpoint de caixa postal em ``MensagemCaixaPostal``."""
    domicilio = (row.get("Domicilio") or "").strip() or None
    categoria = (row.get("Categoria") or "").strip() or None
    return MensagemCaixaPostal(
        orgao=domicilio or categoria or "Caixa postal",
        assunto=unescape((row.get("Assunto") or "").strip()) or "(sem assunto)",
        categoria=categoria,
        empresa=(row.get("EmpresaNome") or "").strip() or None,
        cnpj=normalize_cnpj(row.get("EmpresaInscricaoFederal")),
        remetente=unescape((row.get("Remetente") or "").strip()) or None,
        relevante=row.get("Relevancia") == 1,
        data_postagem=parse_brazilian_date(row.get("EnviadaEm")),
        prazo_ciencia=parse_brazilian_date(row.get("ExibidaAte")),
        lida=leitura_is_lida(row.get("Leitura")),
        nsu=(str(row["Nsu"]).strip() if row.get("Nsu") else None),
        url=unescape((row.get("LinkMensagem") or "").strip()) or None,
    )


def _base_url(portal_url: str) -> str:
    parsed = urlparse(portal_url)
    if not parsed.scheme or not parsed.netloc:
        raise QuestorPortalError(f"URL do Questor inválida: {portal_url!r}")
    return f"{parsed.scheme}://{parsed.netloc}/"


def _login(page: Any, options: QuestorPortalOptions) -> None:
    page.goto(options.portal_url, wait_until=PAGE_LOAD_WAIT_UNTIL, timeout=DEFAULT_TIMEOUT_MS)
    page.wait_for_timeout(2500)
    # Consentimento de cookies (bloqueia a navegação se não aceito).
    consent = page.locator("text=PERMITIR")
    if consent.count():
        consent.first.click()
        page.wait_for_timeout(800)

    email = page.locator("#Email")
    senha = page.locator("#SenhaEntrar")
    if not email.count() or not senha.count():
        raise QuestorPortalError("Formulário de login do Questor não encontrado.")
    email.first.fill(options.login)
    senha.first.fill(options.password)

    for selector in ("button:has-text('ENTRAR')", "text=ENTRAR", "input[type=submit]"):
        button = page.locator(selector)
        if button.count():
            button.first.click()
            break
    else:
        raise QuestorPortalError("Botão ENTRAR não encontrado no login do Questor.")
    page.wait_for_timeout(7000)

    if "areatrabalho" not in page.url and "escritorio" not in page.url:
        raise QuestorPortalError(
            "Login no Questor não confirmado (verifique usuário/senha).",
        )


def _fetch_dataset(page: Any, base_url: str, endpoint: str, *, take: int) -> list[dict[str, Any]]:
    response = page.request.post(
        base_url + endpoint,
        data=f"skip=0&take={take}&requireTotalCount=true",
        headers={
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "x-requested-with": "XMLHttpRequest",
        },
    )
    if response.status != 200:
        raise QuestorPortalError(f"Endpoint {endpoint} respondeu HTTP {response.status}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise QuestorPortalError(f"Endpoint {endpoint} não devolveu JSON.") from exc
    data = payload.get("data")
    if not isinstance(data, list):
        raise QuestorPortalError(f"Endpoint {endpoint} sem campo 'data'.")
    return data


def fetch_questor_snapshot(options: QuestorPortalOptions) -> QuestorSnapshot:
    """Login no Questor e coleta certidões + caixa postal via API interna."""
    if not options.portal_url:
        raise QuestorPortalError("URL do Questor não configurada.")
    base_url = _base_url(options.portal_url)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=options.headless)
        context = browser.new_context()
        page = context.new_page()
        try:
            _login(page, options)
            certidoes_rows = _fetch_dataset(
                page, base_url, CERTIDOES_ENDPOINT, take=options.take,
            )
            mensagens_rows = _fetch_dataset(
                page, base_url, CAIXA_POSTAL_ENDPOINT, take=options.take,
            )
        except PlaywrightTimeoutError as exc:
            raise QuestorPortalError("Questor não respondeu a tempo durante o acesso.") from exc
        finally:
            browser.close()

    certidoes = tuple(certidao_from_api_row(row) for row in certidoes_rows)
    mensagens = tuple(mensagem_from_api_row(row) for row in mensagens_rows)
    return QuestorSnapshot(
        captured_at=datetime.now(UTC),
        empresa=options.empresa,
        cnpj=normalize_cnpj(options.cnpj),
        certidoes=certidoes,
        mensagens=mensagens,
    )
