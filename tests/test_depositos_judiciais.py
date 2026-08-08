"""Testes do inventário de depósitos judiciais (regras offline)."""

from decimal import Decimal

from classificacao_procons.juridico.depositos.classify import (
    classify_document_text,
    infer_deposit_purpose,
)
from classificacao_procons.juridico.depositos.fields import (
    extract_amount_brl,
    extract_process_number,
)
from classificacao_procons.juridico.depositos.models import DepositPurpose, DocumentKind
from classificacao_procons.juridico.depositos.path_rules import (
    should_analyze_pdf,
    should_skip_pdf_by_path,
)


def test_should_skip_comprovante_entrega_path() -> None:
    path = "Maria/Informações/Comprovante de entrega.pdf"
    assert should_skip_pdf_by_path(path) is True
    assert should_analyze_pdf(drive_path=path, file_name="Comprovante de entrega.pdf") is False


def test_should_analyze_guia_sem_extensao_em_pasta_pagamento() -> None:
    path = "João/pet. 003 - pagamento condenacao/2 - guia dep judicial"
    assert should_analyze_pdf(drive_path=path, file_name="2 - guia dep judicial") is True


def test_classify_deposito_pelo_texto_da_guia() -> None:
    text = "GUIA DE DEPÓSITO JUDICIAL\nConta judicial\nCódigo de barras"
    assert classify_document_text(text) == DocumentKind.JUDICIAL_DEPOSIT


def test_classify_custas_sem_confundir_com_deposito() -> None:
    text = "Guia de recolhimento de custas processuais e taxa judiciária"
    assert classify_document_text(text) == DocumentKind.COURT_FEES


def test_extract_process_number_and_amount() -> None:
    text = "Processo 0822560-79.2025.8.19.0208 valor R$ 1.205,93"
    assert extract_process_number(text) == "0822560-79.2025.8.19.0208"
    assert extract_amount_brl(text) == Decimal("1205.93")


def test_infer_condemnation_from_path() -> None:
    purpose = infer_deposit_purpose(
        text="comprovante de pagamento",
        drive_path="Ana/pet. 003 - pagamento condenacao/guia.pdf",
    )
    assert purpose == DepositPurpose.CONDEMNATION
