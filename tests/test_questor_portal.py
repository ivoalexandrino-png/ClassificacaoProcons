"""Testes das conversões da API interna do Questor (sem navegador)."""

from datetime import date

from classificacao_procons.questor.portal import (
    _base_url,
    certidao_from_api_row,
    mensagem_from_api_row,
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
