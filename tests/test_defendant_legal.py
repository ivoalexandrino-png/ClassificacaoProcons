"""Testes dos dados cadastrais da reclamada nas respostas Procon."""

from classificacao_procons.llm.defendant_legal import (
    replace_unauthorized_cnpjs,
    resolve_defendant_legal_profile,
)

B4A_DEFAULT_CNPJ = "13.475.001/0001-34"
MMKT_DEFAULT_CNPJ = "15.481.147/0001-18"


def test_should_use_default_b4a_cnpj_when_complaint_has_no_cnpj() -> None:
    profile = resolve_defendant_legal_profile(complaint_text="Reclamação contra glam clube.")
    assert profile.cnpj == B4A_DEFAULT_CNPJ
    assert profile.entity_id == "b4a"


def test_should_prefer_b4a_cnpj_from_complaint_text() -> None:
    profile = resolve_defendant_legal_profile(
        complaint_text="Fornecedor CNPJ 13.475.001/0002-15 responsável pelo serviço.",
    )
    assert profile.cnpj == "13.475.001/0002-15"
    assert profile.entity_id == "b4a"


def test_should_resolve_mmkt_from_complaint_keyword() -> None:
    profile = resolve_defendant_legal_profile(
        complaint_text="Reclamação contra a MMKT / Men's Market.",
    )
    assert profile.entity_id == "mmkt"
    assert profile.cnpj == MMKT_DEFAULT_CNPJ
    assert "MMKT" in profile.legal_name


def test_should_resolve_mmkt_from_cnpj_in_complaint() -> None:
    profile = resolve_defendant_legal_profile(
        complaint_text="Fornecedor inscrito no CNPJ 15.481.147/0001-18.",
    )
    assert profile.entity_id == "mmkt"
    assert profile.cnpj == MMKT_DEFAULT_CNPJ


def test_should_replace_hallucinated_cnpj_in_b4a_response() -> None:
    profile = resolve_defendant_legal_profile(complaint_text="")
    text = (
        "B4A SERVIÇOS DE TECNOLOGIA E COMÉRCIO S.A., inscrita no CNPJ 15.688.793/0001-23, "
        "vem apresentar resposta."
    )
    fixed = replace_unauthorized_cnpjs(text, profile=profile)
    assert "15.688.793/0001-23" not in fixed
    assert B4A_DEFAULT_CNPJ in fixed


def test_should_replace_hallucinated_cnpj_in_mmkt_response() -> None:
    profile = resolve_defendant_legal_profile(complaint_text="Reclamação MMKT.")
    text = (
        "MMKT COMÉRCIO DE PRODUTOS DE BELEZA, CNPJ 13.475.001/0001-34, "
        "apresenta resposta administrativa."
    )
    fixed = replace_unauthorized_cnpjs(text, profile=profile)
    assert "13.475.001/0001-34" not in fixed
    assert MMKT_DEFAULT_CNPJ in fixed
