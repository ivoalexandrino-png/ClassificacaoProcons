"""Testes de mapeamento de colunas do Monday.com."""

from datetime import date

from classificacao_procons.monday.mapping import (
    MondayColumn,
    build_column_values,
    map_procon_cause_to_monday_status_label,
    resolve_field_for_column,
)


class TestMondayColumnMapping:
    def test_should_map_portuguese_column_titles(self) -> None:
        assert resolve_field_for_column("CPF") == "consumer_cpf"
        assert resolve_field_for_column("Número CIP/FA") == "protocol_number"
        assert resolve_field_for_column("Link PDF Drive") == "pdf_url"
        assert resolve_field_for_column("Notificação Procon") == "pdf_url"
        assert resolve_field_for_column("Procon/Órgão") == "state"
        assert resolve_field_for_column("Prazo SAC") == "sac_deadline"
        assert resolve_field_for_column("Prazo Jurídico") == "legal_deadline"

    def test_should_map_laura_cause_to_cancelamento_label(self) -> None:
        cause = (
            "Demais ServiçosServiços de Beleza e Cuidados PessoaisContrato / Oferta"
            "Dificuldade para alterar ou cancelar o contrato /serviço"
        )
        assert map_procon_cause_to_monday_status_label(cause) == "Problemas com Cancelamento"

    def test_should_skip_unmapped_cause_on_status_column(self) -> None:
        columns = [
            MondayColumn(id="status_cause", title="Classificação", column_type="status"),
        ]
        values = build_column_values(
            columns,
            consumer_name="MARIA",
            state="SP",
            pdf_url=None,
            protocol_number="1653213/2026",
            consumer_cpf="12345678901",
            complaint_date=None,
            sac_deadline=None,
            legal_deadline=None,
            cause="Texto sem palavra-chave conhecida",
        )
        assert values == {}

    def test_should_build_column_values_by_type(self) -> None:
        columns = [
            MondayColumn(id="text_cpf", title="CPF", column_type="text"),
            MondayColumn(id="link_pdf", title="Link PDF", column_type="link"),
            MondayColumn(id="date_sac", title="Prazo SAC", column_type="date"),
            MondayColumn(id="status_uf", title="Estado", column_type="status"),
        ]

        values = build_column_values(
            columns,
            consumer_name="MARIA",
            state="SP",
            pdf_url="https://drive.google.com/file/abc/view",
            protocol_number="1653213/2026",
            consumer_cpf="12345678901",
            complaint_date=date(2026, 7, 14),
            sac_deadline=date(2026, 7, 19),
            legal_deadline=date(2026, 7, 20),
            cause="Atraso na entrega",
        )

        assert values["text_cpf"] == "12345678901"
        assert values["link_pdf"] == {
            "url": "https://drive.google.com/file/abc/view",
            "text": "PDF Procon",
        }
        assert values["date_sac"] == {"date": "2026-07-19"}
        assert values["status_uf"] == {"label": "SP"}

    def test_should_ignore_unknown_columns(self) -> None:
        columns = [MondayColumn(id="text_extra", title="Observações internas", column_type="text")]

        values = build_column_values(
            columns,
            consumer_name="MARIA",
            state="SP",
            pdf_url=None,
            protocol_number="1653213/2026",
            consumer_cpf="12345678901",
            complaint_date=None,
            sac_deadline=None,
            legal_deadline=None,
            cause="",
        )

        assert values == {}
