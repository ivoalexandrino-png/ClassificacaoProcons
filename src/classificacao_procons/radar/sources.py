"""Registro das principais fontes de fomento monitoradas pelo radar.

As URLs apontam para páginas públicas oficiais das agências. Quando ``feed_url``
não é informado, o coletor usa a página inicial (``url``) e o endpoint de
oportunidades precisa ser calibrado na primeira execução assistida — mesma
convenção do scraper do Questor. As áreas são o "chute inicial" de cada fonte; a
classificação fina por edital é feita em ``parser.classify_areas``.
"""

from __future__ import annotations

from classificacao_procons.radar.models import Area, FundingSource, Scope

# Fontes nacionais (Brasil).
_NACIONAIS: tuple[FundingSource, ...] = (
    FundingSource(
        key="cnpq",
        name="CNPq — Conselho Nacional de Desenvolvimento Científico e Tecnológico",
        scope="nacional",
        url="https://www.gov.br/cnpq/pt-br/acesso-a-informacao/acoes-e-programas/servicos/chamadas-publicas",
        areas=("multidisciplinar",),
    ),
    FundingSource(
        key="capes",
        name="CAPES — Coordenação de Aperfeiçoamento de Pessoal de Nível Superior",
        scope="nacional",
        url="https://www.gov.br/capes/pt-br/acesso-a-informacao/acoes-e-programas/editais",
        areas=("educacao", "multidisciplinar"),
    ),
    FundingSource(
        key="finep",
        name="FINEP — Financiadora de Estudos e Projetos",
        scope="nacional",
        url="http://www.finep.gov.br/chamadas-publicas",
        areas=("multidisciplinar", "administracao"),
    ),
    FundingSource(
        key="fapesp",
        name="FAPESP — Fundação de Amparo à Pesquisa do Estado de São Paulo",
        scope="nacional",
        url="https://fapesp.br/chamadas",
        areas=("multidisciplinar",),
    ),
    FundingSource(
        key="faperj",
        name="FAPERJ — Fundação de Amparo à Pesquisa do Estado do Rio de Janeiro",
        scope="nacional",
        url="https://www.faperj.br/?id=25.2.5",
        areas=("multidisciplinar",),
    ),
    FundingSource(
        key="fapemig",
        name="FAPEMIG — Fundação de Amparo à Pesquisa do Estado de Minas Gerais",
        scope="nacional",
        url="http://www.fapemig.br/pt/chamadas_abertas_oportunidades_fapemig/",
        areas=("multidisciplinar",),
    ),
    FundingSource(
        key="confap",
        name="CONFAP — Conselho Nacional das Fundações Estaduais de Amparo à Pesquisa",
        scope="nacional",
        url="https://confap.org.br/news/",
        areas=("multidisciplinar",),
    ),
    FundingSource(
        key="ms-decit",
        name="Ministério da Saúde — DECIT (fomento à pesquisa em saúde)",
        scope="nacional",
        url="https://www.gov.br/saude/pt-br/composicao/sectics/decit",
        areas=("saude",),
    ),
    FundingSource(
        key="fiocruz",
        name="Fiocruz — Fundação Oswaldo Cruz",
        scope="nacional",
        url="https://portal.fiocruz.br/editais",
        areas=("saude",),
    ),
    FundingSource(
        key="ipea",
        name="IPEA — Instituto de Pesquisa Econômica Aplicada",
        scope="nacional",
        url="https://www.ipea.gov.br/portal/editais",
        areas=("administracao", "direito"),
    ),
    FundingSource(
        key="cnj-editais",
        name="CNJ — Conselho Nacional de Justiça (editais e pesquisa)",
        scope="nacional",
        url="https://www.cnj.jus.br/transparencia-e-prestacao-de-contas/gestao-orcamentaria-e-financeira/editais/",
        areas=("direito",),
    ),
)

# Fontes internacionais.
_INTERNACIONAIS: tuple[FundingSource, ...] = (
    FundingSource(
        key="horizon-europe",
        name="Comissão Europeia — Horizon Europe (Funding & Tenders Portal)",
        scope="internacional",
        url="https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/home",
        areas=("multidisciplinar",),
    ),
    FundingSource(
        key="erc",
        name="ERC — European Research Council",
        scope="internacional",
        url="https://erc.europa.eu/apply-grant/calls-proposals",
        areas=("multidisciplinar",),
    ),
    FundingSource(
        key="nih",
        name="NIH — US National Institutes of Health (Grants)",
        scope="internacional",
        url="https://grants.nih.gov/funding/searchguide/index.html",
        areas=("saude",),
    ),
    FundingSource(
        key="nsf",
        name="NSF — US National Science Foundation (Funding)",
        scope="internacional",
        url="https://www.nsf.gov/funding/opportunities",
        areas=("multidisciplinar",),
    ),
    FundingSource(
        key="wellcome",
        name="Wellcome Trust — Grant funding",
        scope="internacional",
        url="https://wellcome.org/grant-funding",
        areas=("saude",),
    ),
    FundingSource(
        key="gates",
        name="Bill & Melinda Gates Foundation — Grant opportunities",
        scope="internacional",
        url="https://www.gatesfoundation.org/about/how-we-work/grant-opportunities",
        areas=("saude",),
    ),
    FundingSource(
        key="open-society",
        name="Open Society Foundations — Grants",
        scope="internacional",
        url="https://www.opensocietyfoundations.org/grants",
        areas=("direito",),
    ),
    FundingSource(
        key="ford",
        name="Ford Foundation — Grants",
        scope="internacional",
        url="https://www.fordfoundation.org/work/our-grants/",
        areas=("direito", "administracao"),
    ),
    FundingSource(
        key="unesco",
        name="UNESCO — Calls and opportunities",
        scope="internacional",
        url="https://www.unesco.org/en/opportunities",
        areas=("educacao",),
    ),
    FundingSource(
        key="daad",
        name="DAAD — Serviço Alemão de Intercâmbio Acadêmico",
        scope="internacional",
        url="https://www.daad.org.br/pt/encontre-financiamentos/",
        areas=("educacao", "multidisciplinar"),
    ),
    FundingSource(
        key="fulbright-br",
        name="Fulbright Brasil — Bolsas e oportunidades",
        scope="internacional",
        url="https://fulbright.org.br/bolsas/",
        areas=("educacao", "multidisciplinar"),
    ),
    FundingSource(
        key="british-council",
        name="British Council Brasil — Oportunidades",
        scope="internacional",
        url="https://www.britishcouncil.org.br/programas",
        areas=("educacao", "multidisciplinar"),
    ),
    FundingSource(
        key="iadb",
        name="IDB/BID — Banco Interamericano de Desenvolvimento",
        scope="internacional",
        url="https://www.iadb.org/en/how-we-can-work-together/civil-society/funding-opportunities",
        areas=("administracao",),
    ),
)

DEFAULT_SOURCES: tuple[FundingSource, ...] = _NACIONAIS + _INTERNACIONAIS

_SOURCES_BY_KEY: dict[str, FundingSource] = {source.key: source for source in DEFAULT_SOURCES}


def all_sources() -> tuple[FundingSource, ...]:
    """Todas as fontes registradas (nacionais + internacionais)."""
    return DEFAULT_SOURCES


def source_by_key(key: str) -> FundingSource | None:
    """Devolve a fonte pela chave, ou ``None`` se não existir."""
    return _SOURCES_BY_KEY.get(key)


def get_sources(
    *,
    scope: Scope | None = None,
    area: Area | None = None,
    keys: tuple[str, ...] | None = None,
    only_enabled: bool = True,
) -> tuple[FundingSource, ...]:
    """Filtra as fontes por abrangência, área e/ou chaves.

    Uma fonte marcada como ``multidisciplinar`` casa com qualquer ``area``, pois
    publica editais de todas as áreas (a filtragem fina é por edital).
    """
    selected: list[FundingSource] = []
    for source in DEFAULT_SOURCES:
        if only_enabled and not source.enabled:
            continue
        if keys is not None and source.key not in keys:
            continue
        if scope is not None and source.scope != scope:
            continue
        if area is not None and area not in source.areas and "multidisciplinar" not in source.areas:
            continue
        selected.append(source)
    return tuple(selected)
