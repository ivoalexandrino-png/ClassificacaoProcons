"""Testes de mapeamento Monday para contratos."""

from datetime import date

from classificacao_procons.contratos.gemini_extractor import ContractMetadata
from classificacao_procons.contratos.monday_contracts import _build_contratos_column_values
from classificacao_procons.monday.mapping import MondayColumn


class TestContratosMondayColumnValues:
    def test_should_format_column_values_by_type(self) -> None:
        columns = [
            MondayColumn(id="empresa", title="Empresa", column_type="status"),
            MondayColumn(id="cnpj", title="CNPJ", column_type="text"),
            MondayColumn(id="tipo", title="Tipo de contrato", column_type="status"),
            MondayColumn(id="data", title="Data do contrato", column_type="date"),
            MondayColumn(id="termino", title="Término", column_type="date"),
            MondayColumn(id="contrato", title="Contrato", column_type="link"),
            MondayColumn(id="vigencia", title="Vigência", column_type="status"),
            MondayColumn(id="obs", title="Observações", column_type="long_text"),
        ]
        metadata = ContractMetadata(
            counterparty_name="Amby Natural",
            counterparty_cnpj="12.345.678/0001-90",
            contract_type="Prestação de Serviços",
            company="B4A",
            start_date=date(2026, 1, 1),
            end_date=date(2027, 1, 1),
            property_name=None,
            summary="Contrato de parceria B2B.",
        )

        values = _build_contratos_column_values(
            columns,
            metadata=metadata,
            signed_pdf_url="https://drive.google.com/file/abc/view",
            document_name="Contrato B2B Amby Natural",
        )

        assert values["empresa"] == {"label": "B4A"}
        assert values["cnpj"] == "12.345.678/0001-90"
        assert values["tipo"] == {"label": "Prestação de Serviços"}
        assert values["data"] == {"date": "2026-01-01"}
        assert values["termino"] == {"date": "2027-01-01"}
        assert values["contrato"] == {
            "url": "https://drive.google.com/file/abc/view",
            "text": "Contrato B2B Amby Natural",
        }
        assert values["vigencia"] == {"label": "Vigente"}
        assert values["obs"] == {"text": "Contrato de parceria B2B."}
