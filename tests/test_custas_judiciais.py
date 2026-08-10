"""Testes do inventário de custas processuais (regras offline)."""

from decimal import Decimal

from classificacao_procons.juridico.custas.aggregate import build_custas_process_rows
from classificacao_procons.juridico.custas.classify import (
    infer_fee_type,
    is_court_fees_document,
)
from classificacao_procons.juridico.custas.dedupe import dedupe_court_fee_records
from classificacao_procons.juridico.custas.fields import extract_custas_amount_brl
from classificacao_procons.juridico.custas.models import (
    CourtFeeRecord,
    CourtFeeType,
    ExtractionConfidence,
)
from classificacao_procons.juridico.custas.path_rules import (
    should_analyze_pdf,
    should_skip_pdf_by_path_for_custas,
)


def test_custas_does_not_skip_recurso_inominado_path() -> None:
    path = "Maria/Recurso inominado/guia custas.pdf"
    assert should_skip_pdf_by_path_for_custas(path) is False
    assert should_analyze_pdf(drive_path=path, file_name="guia custas.pdf") is True


def test_custas_skips_entrega_path() -> None:
    path = "Maria/Informações/Comprovante de entrega.pdf"
    assert should_skip_pdf_by_path_for_custas(path) is True
    assert should_analyze_pdf(drive_path=path, file_name="Comprovante de entrega.pdf") is False


def test_custas_blocks_deposit_filename() -> None:
    path = "João/pet. 003 - pagamento condenacao/guia dep judicial.pdf"
    assert should_analyze_pdf(drive_path=path, file_name="guia dep judicial.pdf") is False


def test_is_court_fees_document_recognizes_taxa_judiciaria() -> None:
    text = "Guia de recolhimento de custas processuais e taxa judiciária"
    assert is_court_fees_document(text) is True


def test_is_court_fees_document_rejects_deposito_judicial() -> None:
    text = "Guia de depósito judicial — conta judicial SISTEMA DJO"
    assert is_court_fees_document(text) is False


def test_infer_fee_type_appeal_from_recurso_path() -> None:
    fee_type = infer_fee_type(
        text="comprovante de pagamento",
        drive_path="Ana/Recurso inominado/comprov custas.pdf",
    )
    assert fee_type == CourtFeeType.APPEAL


def test_dedupe_prefers_comprovante_over_guia() -> None:
    guia = CourtFeeRecord(
        consumer_folder="Ana",
        drive_file_id="a",
        drive_path="Ana/custas/guia.pdf",
        drive_url=None,
        process_number="0822560-79.2025.8.19.0208",
        amount_brl=Decimal("120.00"),
        payment_date="2025-01-10",
        fee_type=CourtFeeType.INITIAL,
        extraction_method="pypdf",
        confidence=ExtractionConfidence.MEDIUM,
    )
    comprov = CourtFeeRecord(
        consumer_folder="Ana",
        drive_file_id="b",
        drive_path="Ana/custas/comprov pagamento.pdf",
        drive_url=None,
        process_number="0822560-79.2025.8.19.0208",
        amount_brl=Decimal("120.00"),
        payment_date="2025-01-10",
        fee_type=CourtFeeType.INITIAL,
        extraction_method="pypdf",
        confidence=ExtractionConfidence.HIGH,
    )
    deduped = dedupe_court_fee_records([guia, comprov])
    assert len(deduped) == 1
    assert deduped[0].drive_file_id == "b"


def test_aggregate_sums_by_process_number() -> None:
    records = [
        CourtFeeRecord(
            consumer_folder="Ana",
            drive_file_id="1",
            drive_path="Ana/custas/a.pdf",
            drive_url=None,
            process_number="0822560-79.2025.8.19.0208",
            amount_brl=Decimal("50.00"),
            payment_date=None,
            fee_type=CourtFeeType.INITIAL,
            extraction_method="pypdf",
            confidence=ExtractionConfidence.HIGH,
        ),
        CourtFeeRecord(
            consumer_folder="Ana",
            drive_file_id="2",
            drive_path="Ana/custas/b.pdf",
            drive_url=None,
            process_number="0822560-79.2025.8.19.0208",
            amount_brl=Decimal("70.25"),
            payment_date=None,
            fee_type=CourtFeeType.APPEAL,
            extraction_method="pypdf",
            confidence=ExtractionConfidence.HIGH,
        ),
    ]
    rows = build_custas_process_rows(records=records)
    assert len(rows) == 1
    assert rows[0].total_court_fees_brl == Decimal("120.25")
    assert rows[0].fee_line_count == 2


def test_extract_custas_amount_prefers_valor_documento_not_causa() -> None:
    text = (
        "VALOR DA CAUSA: R$ 20.000,00\n"
        "R$ 645,80VALOR TOTAL\n"
        "(=) Valor Documento\n"
        "R$ 645,80\n"
    )
    extracted = extract_custas_amount_brl(text)
    assert extracted.amount_brl == Decimal("645.80")
    assert extracted.reference_base_brl == Decimal("20000.00")


def test_extract_custas_amount_total_dotted_line() -> None:
    text = "VALOR DA CAUSA: R$ 11.241,36\nTOTAL: ................................512,00\n"
    extracted = extract_custas_amount_brl(text)
    assert extracted.amount_brl == Decimal("512.00")


def test_extract_amount_on_custas_guia_text() -> None:
    text = "Custas processuais — valor R$ 89,40"
    extracted = extract_custas_amount_brl(text)
    assert extracted.amount_brl == Decimal("89.40")
