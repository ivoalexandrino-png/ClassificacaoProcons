"""Testes dos dados cadastrais da reclamada nas respostas Procon."""

from classificacao_procons.llm.defendant_legal import (
    DEFAULT_CNPJ,
    replace_unauthorized_cnpjs,
    resolve_defendant_legal_profile,
)


def test_should_use_default_b4a_cnpj_when_complaint_has_no_cnpj() -> None:
    profile = resolve_defendant_legal_profile(complaint_text="Reclamação contra glam clube.")
    assert profile.cnpj == DEFAULT_CNPJ


def test_should_prefer_b4a_cnpj_from_complaint_text() -> None:
    profile = resolve_defendant_legal_profile(
        complaint_text="Fornecedor CNPJ 13.475.001/0002-15 responsável pelo serviço.",
    )
    assert profile.cnpj == "13.475.001/0002-15"


def test_should_replace_hallucinated_cnpj_in_response() -> None:
    profile = resolve_defendant_legal_profile(complaint_text="")
    text = (
        "B4A SERVIÇOS DE TECNOLOGIA E COMÉRCIO S.A., inscrita no CNPJ 15.688.793/0001-23, "
        "vem apresentar resposta."
    )
    fixed = replace_unauthorized_cnpjs(text, profile=profile)
    assert "15.688.793/0001-23" not in fixed
    assert DEFAULT_CNPJ in fixed
