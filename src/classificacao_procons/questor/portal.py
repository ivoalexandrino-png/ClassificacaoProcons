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
from datetime import UTC, date, datetime
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
CERTIDAO_RENEW_ENDPOINT: Final = "escritorio/cnd/certidaoempresa/RenovarCertidao"
CERTIDAO_HISTORICO_ENDPOINT: Final = "escritorio/cnd/historicocertidao/listar"
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
    # Recaptura: antes de ler, dispara "Renovar Certidão" para as certidões não
    # regulares (assíncrono no Questor) e aguarda ``refresh_wait_seconds`` antes de
    # reler. Reduz o risco de situação desatualizada (ex.: CND já emitida no órgão).
    refresh_stale_certidoes: bool = False
    refresh_wait_seconds: int = 120
    renew_warn_days: int = 15

# SituacaoCertidao == 1 é "Regular"; as demais (Irregular/Neutro/Falha/Restrição)
# podem estar defasadas e valem uma recaptura.
_REGULAR_SITUACAO_CODE: Final = 1


def select_stale_certidao_ids(rows: list[dict[str, Any]]) -> list[int]:
    """IDs das certidões não regulares (candidatas a recaptura)."""
    ids: list[int] = []
    for row in rows:
        if row.get("SituacaoCertidao") == _REGULAR_SITUACAO_CODE:
            continue
        raw_id = row.get("Id")
        if raw_id is None:
            continue
        try:
            ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue
    return ids


def select_certidoes_to_renew(
    rows: list[dict[str, Any]],
    *,
    today: date | None = None,
    warn_days: int = 15,
) -> list[int]:
    """IDs a recapturar: não regulares OU vencidas/a vencer (renovação preventiva)."""
    reference = today or date.today()
    ids: list[int] = []
    for row in rows:
        raw_id = row.get("Id")
        if raw_id is None:
            continue
        renew = row.get("SituacaoCertidao") != _REGULAR_SITUACAO_CODE
        if not renew:
            venc = parse_brazilian_date(row.get("CertidaoDataVencimento"))
            if venc is None or (venc - reference).days <= warn_days:
                renew = True
        if renew:
            try:
                ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
    return ids


def trigger_certidao_refresh(request: Any, base_url: str, cert_id: int) -> bool:
    """Dispara a recaptura de uma certidão. Retorna True se o Questor aceitou.

    ``request`` é um objeto com ``.post(url, headers=...)`` (ex.: ``page.request``).
    """
    response = request.post(
        f"{base_url}{CERTIDAO_RENEW_ENDPOINT}?certidaoEmpresaId={cert_id}",
        headers={"x-requested-with": "XMLHttpRequest"},
    )
    if getattr(response, "status", 200) != 200:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    return bool(payload.get("sucesso"))


def _clean(value: Any) -> str | None:
    return (str(value).strip() or None) if value is not None else None


def certidao_from_api_row(
    row: dict[str, Any],
    historico_row: dict[str, Any] | None = None,
) -> Certidao:
    """Converte uma linha do endpoint de certidões em ``Certidao``.

    ``historico_row`` (última captura no histórico) enriquece com o motivo/situação
    legível (ex.: "Inscrição federal inválida", "Fila de Processamento").
    """
    tipo = (row.get("TipoCertidaoDescricao") or "").strip() or None
    categoria = (row.get("Categoria") or "").strip() or None
    orgao = tipo or categoria or "Certidão"
    diagnostico = status_captura = None
    if historico_row:
        diagnostico = _clean(historico_row.get("Situacao"))
        status_captura = _clean(historico_row.get("ProximaCapturaStr"))
    return Certidao(
        orgao=orgao,
        situacao=situacao_from_questor_code(row.get("SituacaoCertidao")),
        tipo=categoria,
        cnpj=normalize_cnpj(row.get("EmpresaInscricaoFederal")),
        empresa=(row.get("EmpresaNome") or row.get("EmpresaRazaoSocial") or "").strip() or None,
        uf=(row.get("UF") or "").strip() or None,
        data_emissao=parse_brazilian_date(row.get("CertidaoDataEmissao")),
        data_validade=parse_brazilian_date(row.get("CertidaoDataVencimento")),
        protocolo=(row.get("CertidaoProtocolo") or "").strip() or None,
        conferida=(row.get("Conferida") == 1) if row.get("Conferida") is not None else None,
        diagnostico=diagnostico,
        status_captura=status_captura,
    )


def latest_historico_by_certidao(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Mapa CertidaoEmpresaId → última entrada do histórico (por Data)."""
    latest: dict[int, dict[str, Any]] = {}
    for row in rows:
        raw_id = row.get("CertidaoEmpresaId")
        if raw_id is None:
            continue
        try:
            key = int(raw_id)
        except (TypeError, ValueError):
            continue
        data = str(row.get("Data") or "")
        current = latest.get(key)
        if current is None or data > str(current.get("Data") or ""):
            latest[key] = row
    return latest


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
        # ExibidaAte é "exibida até" (data de exibição, às vezes anos no futuro),
        # não um prazo legal de ciência — não usar como prazo para evitar falso
        # positivo. A relevância vem da classificação por assunto.
        prazo_ciencia=None,
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


@dataclass(frozen=True)
class RefreshResult:
    """Resultado do disparo de recaptura de certidões."""

    stale_ids: tuple[int, ...]
    triggered: int


def refresh_stale_certidoes(options: QuestorPortalOptions) -> RefreshResult:
    """Login e dispara a recaptura das certidões não regulares (sem reler/esperar).

    Pensado para a fase de "gatilho" do fluxo em duas etapas: a nova situação
    chega de forma assíncrona (pode levar minutos), então a leitura fica para um
    segundo momento (ex.: o job de leitura ~30 min depois).
    """
    if not options.portal_url:
        raise QuestorPortalError("URL do Questor não configurada.")
    base_url = _base_url(options.portal_url)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=options.headless)
        page = browser.new_context().new_page()
        try:
            _login(page, options)
            rows = _fetch_dataset(page, base_url, CERTIDOES_ENDPOINT, take=options.take)
            stale_ids = select_certidoes_to_renew(rows, warn_days=options.renew_warn_days)
            triggered = sum(
                trigger_certidao_refresh(page.request, base_url, cert_id)
                for cert_id in stale_ids
            )
        except PlaywrightTimeoutError as exc:
            raise QuestorPortalError("Questor não respondeu a tempo durante o acesso.") from exc
        finally:
            browser.close()
    return RefreshResult(stale_ids=tuple(stale_ids), triggered=triggered)


def _row_id(row: dict[str, Any]) -> int | None:
    try:
        return int(row["Id"]) if row.get("Id") is not None else None
    except (TypeError, ValueError):
        return None


def _fetch_historico_map(page: Any, base_url: str, *, take: int) -> dict[int, dict[str, Any]]:
    """Histórico de capturas (GET) → última entrada por certidão. Falha não bloqueia."""
    try:
        response = page.request.get(
            f"{base_url}{CERTIDAO_HISTORICO_ENDPOINT}"
            f"?skip=0&take={take}&requireTotalCount=true",
            headers={"x-requested-with": "XMLHttpRequest"},
        )
        if response.status != 200:
            return {}
        rows = response.json().get("data", [])
    except (ValueError, KeyError):
        return {}
    return latest_historico_by_certidao(rows)


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
            if options.refresh_stale_certidoes:
                stale_ids = select_certidoes_to_renew(
                    certidoes_rows, warn_days=options.renew_warn_days,
                )
                triggered = sum(
                    trigger_certidao_refresh(page.request, base_url, cert_id)
                    for cert_id in stale_ids
                )
                if triggered:
                    # A recaptura é assíncrona; espera limitada e relê as certidões.
                    page.wait_for_timeout(max(0, options.refresh_wait_seconds) * 1000)
                    certidoes_rows = _fetch_dataset(
                        page, base_url, CERTIDOES_ENDPOINT, take=options.take,
                    )
            mensagens_rows = _fetch_dataset(
                page, base_url, CAIXA_POSTAL_ENDPOINT, take=options.take,
            )
            historico_map = _fetch_historico_map(page, base_url, take=options.take)
        except PlaywrightTimeoutError as exc:
            raise QuestorPortalError("Questor não respondeu a tempo durante o acesso.") from exc
        finally:
            browser.close()

    certidoes = tuple(
        certidao_from_api_row(row, historico_map.get(_row_id(row)))
        for row in certidoes_rows
    )
    mensagens = tuple(mensagem_from_api_row(row) for row in mensagens_rows)
    return QuestorSnapshot(
        captured_at=datetime.now(UTC),
        empresa=options.empresa,
        cnpj=normalize_cnpj(options.cnpj),
        certidoes=certidoes,
        mensagens=mensagens,
    )
