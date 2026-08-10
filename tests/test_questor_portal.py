"""Testes das conversões da API interna do Questor (sem navegador)."""

from datetime import date

from classificacao_procons.questor.portal import (
    _base_url,
    certidao_from_api_row,
    mensagem_from_api_row,
    select_stale_certidao_ids,
    trigger_certidao_refresh,
)


def test_certidao_from_api_row_should_map_fields_and_enum() -> None:
    row = {
        "EmpresaNome": "B4A SERVICOS DE TECNOLOGIA E COMERCIO S. A.",
        "EmpresaInscricaoFederal": "13475001000134",
        "Categoria": "Estadual",
        "UF": "SE",
        "TipoCertidaoDescricao": "Sergipe - Cadastro Sintegra",
        "CertidaoDataEmissao": "2025-12-02T00:23:18",
        "CertidaoDataVencimento": "2026-12-02T00:00:00",
        "SituacaoCertidao": 1,
        "CertidaoProtocolo": "HABILITADO",
    }
    cert = certidao_from_api_row(row)
    assert cert.orgao == "Sergipe - Cadastro Sintegra"
    assert cert.situacao == "negativa"  # 1 = Regular
    assert cert.cnpj == "13475001000134"
    assert cert.empresa.startswith("B4A")
    assert cert.uf == "SE"
    assert cert.data_emissao == date(2025, 12, 2)
    assert cert.data_validade == date(2026, 12, 2)


def test_certidao_from_api_row_should_flag_irregular() -> None:
    cert = certidao_from_api_row(
        {"TipoCertidaoDescricao": "Federal - PGFN", "SituacaoCertidao": 0},
    )
    assert cert.situacao == "positiva"  # 0 = Irregular


def test_mensagem_from_api_row_should_map_read_and_relevance() -> None:
    row = {
        "EmpresaNome": "MMKT COMERCIO",
        "EmpresaInscricaoFederal": "15481147000118",
        "Categoria": "Estadual",
        "Domicilio": "São Paulo",
        "Relevancia": 0,
        "Leitura": 2,
        "Remetente": "GOVERNO DO ESTADO DE SÃO PAULO",
        "Assunto": "Outros",
        "LinkMensagem": "https://www.dec.fazenda.sp.gov.br/DEC/UCLogin/login.aspx",
        "EnviadaEm": "2026-05-14T00:00:00",
        "ExibidaAte": None,
        "Nsu": "20260514230422001",
    }
    msg = mensagem_from_api_row(row)
    assert msg.orgao == "São Paulo"
    assert msg.assunto == "Outros"
    assert msg.lida is True  # Leitura 2 = Lido
    assert msg.relevante is False
    assert msg.data_postagem == date(2026, 5, 14)
    assert msg.nsu == "20260514230422001"
    assert msg.cnpj == "15481147000118"


def test_mensagem_from_api_row_should_treat_leitura_zero_as_unread() -> None:
    msg = mensagem_from_api_row({"Domicilio": "e-CAC", "Leitura": 0, "Relevancia": 1})
    assert msg.lida is False
    assert msg.relevante is True


def test_base_url_should_extract_scheme_and_host() -> None:
    assert _base_url("https://b4a.zen.questor.com.br/login") == "https://b4a.zen.questor.com.br/"


def test_select_stale_certidao_ids_returns_non_regular() -> None:
    rows = [
        {"Id": 1, "SituacaoCertidao": 1},  # Regular → fora
        {"Id": 2, "SituacaoCertidao": 0},  # Irregular → dentro
        {"Id": 3, "SituacaoCertidao": 5},  # Restrição → dentro
        {"Id": 4, "SituacaoCertidao": 3},  # Falha → dentro
        {"SituacaoCertidao": 0},  # sem Id → ignorado
    ]
    assert select_stale_certidao_ids(rows) == [2, 3, 4]


def test_select_certidoes_to_renew_includes_expiring_and_expired() -> None:
    from datetime import date

    from classificacao_procons.questor.portal import select_certidoes_to_renew

    rows = [
        {"Id": 1, "SituacaoCertidao": 1, "CertidaoDataVencimento": "2026-12-31T00:00:00"},
        {"Id": 2, "SituacaoCertidao": 0, "CertidaoDataVencimento": "2027-01-01T00:00:00"},
        {"Id": 3, "SituacaoCertidao": 1, "CertidaoDataVencimento": "2026-08-20T00:00:00"},
        {"Id": 4, "SituacaoCertidao": 1, "CertidaoDataVencimento": "2026-07-01T00:00:00"},
        {"Id": 5, "SituacaoCertidao": 1, "CertidaoDataVencimento": None},
    ]
    # 1 regular/vigente → fora; 2 irregular; 3 a vencer; 4 vencida; 5 sem validade
    ids = select_certidoes_to_renew(rows, today=date(2026, 8, 10), warn_days=15)
    assert ids == [2, 3, 4, 5]


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    def json(self):
        return self._payload


class _FakeRequest:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def post(self, url, headers=None):
        self.calls.append(url)
        return self._response


def test_trigger_certidao_refresh_success() -> None:
    request = _FakeRequest(_FakeResponse({"sucesso": True}))
    ok = trigger_certidao_refresh(request, "https://b4a.zen.questor.com.br/", 83)
    assert ok is True
    assert request.calls == [
        "https://b4a.zen.questor.com.br/escritorio/cnd/certidaoempresa/"
        "RenovarCertidao?certidaoEmpresaId=83"
    ]


def test_trigger_certidao_refresh_failure() -> None:
    request = _FakeRequest(_FakeResponse({"sucesso": False}))
    assert trigger_certidao_refresh(request, "https://b4a.zen.questor.com.br/", 1) is False


def test_latest_historico_and_diagnostico_enrichment() -> None:
    from classificacao_procons.questor.portal import latest_historico_by_certidao

    hist = [
        {"CertidaoEmpresaId": 15, "Data": "2025-04-24T20:00", "Situacao": "antigo",
         "ProximaCapturaStr": "x"},
        {"CertidaoEmpresaId": 15, "Data": "2026-08-10T15:26", "Situacao": "Fila de Processamento",
         "ProximaCapturaStr": "Aguardando Captura"},
    ]
    latest = latest_historico_by_certidao(hist)
    assert latest[15]["Situacao"] == "Fila de Processamento"

    cert = certidao_from_api_row(
        {"TipoCertidaoDescricao": "PGFN - PJ", "SituacaoCertidao": 5, "Id": 15},
        latest[15],
    )
    assert cert.diagnostico == "Fila de Processamento"
    assert cert.status_captura == "Aguardando Captura"
