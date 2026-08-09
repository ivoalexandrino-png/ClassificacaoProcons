"""Testes do classificador de relevância da caixa postal."""

import pytest

from classificacao_procons.questor.models import MensagemCaixaPostal
from classificacao_procons.questor.relevancia import classify_caixa_message


def _msg(assunto: str, **kwargs) -> MensagemCaixaPostal:
    return MensagemCaixaPostal(orgao="e-CAC", assunto=assunto, **kwargs)


@pytest.mark.parametrize(
    ("assunto", "category", "severity"),
    [
        ("Início de ação fiscal / fiscalização", "fiscalizacao", "critical"),
        ("Notificação de Lançamento de ofício", "lancamento", "critical"),
        ("Auto de Infração nº 999", "lancamento", "critical"),
        ("Intimação para prestar esclarecimentos", "intimacao", "critical"),
        ("Termo de exigência fiscal", "intimacao", "critical"),
        ("Débito em atraso - cobrança", "pagamento", "critical"),
        ("Inscrição em dívida ativa", "pagamento", "critical"),
        ("Vencimento de Certidão Conjunta", "certidao", "warning"),
        ("[e-Processo] Juntada de documentos", "processo", "warning"),
        ("Comunicado Cadin - nº 4057014", "pagamento", "critical"),
        ("Comunica Multa por Atraso na Entrega de Declaração", "lancamento", "critical"),
        ("Comunicação para Compensação de Ofício nº 123", "pagamento", "critical"),
        ("PER/DCOMP 123 - Despacho Decisório", "processo", "warning"),
        ("Programa Nos Conformes", "fiscalizacao", "critical"),
        ("Autorregularização de pendências", "autorregularizacao", "warning"),
        ("PEP - Programa Especial de Parcelamento", "pagamento", "critical"),
    ],
)
def test_should_classify_relevant_subjects(
    assunto: str,
    category: str,
    severity: str,
) -> None:
    result = classify_caixa_message(_msg(assunto))
    assert result is not None
    assert result[0] == category
    assert result[2] == severity


@pytest.mark.parametrize(
    "assunto",
    [
        "Escrituração Fiscal Digital",
        "[DCTF] Original Recepcionada",
        "Orientação Tributária",
        "Bem-vindo ao Caixa Postal!",
        "Outros",
    ],
)
def test_should_ignore_routine_subjects(assunto: str) -> None:
    assert classify_caixa_message(_msg(assunto)) is None


def test_should_consider_remetente_and_categoria() -> None:
    msg = MensagemCaixaPostal(
        orgao="SEFAZ",
        assunto="Comunicado",
        remetente="Delegacia de Fiscalização",
    )
    result = classify_caixa_message(msg)
    assert result is not None
    assert result[0] == "fiscalizacao"


def test_env_extra_keywords_override(monkeypatch) -> None:
    monkeypatch.setenv("QUESTOR_RELEVANCIA_EXTRA", "pagamento:redarf; processo:nota fiscal")
    # "Redarf" normalmente é rotineiro; a env força classificá-lo.
    result = classify_caixa_message(_msg("Redarf Net - Pedido de retificação"))
    assert result is not None
    assert result[0] == "pagamento"
