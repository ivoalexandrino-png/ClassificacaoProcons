"""Testes de mapeamento de colunas do Monday.com."""

from datetime import date

from classificacao_procons.monday.mapping import (
    FIELD_PA_DEADLINE,
    FIELD_PA_GENERATED,
    FIELD_PA_NUMBER,
    FIELD_PA_RESPONDED,
    ORIGIN_LABEL_GLAM_CLUBE,
    ORIGIN_LABEL_GLAM_LOJA,
    ORIGIN_LABEL_MENS_CLUBE,
    ORIGIN_LABEL_MENS_LOJA,
    MondayColumn,
    MondayColumnDetails,
    allowed_labels,
    build_administrative_process_column_values,
    build_column_values,
    map_complaint_to_origin_label,
    map_procon_cause_to_monday_status_label,
    resolve_field_for_column,
    sanitize_column_values,
)


class TestMondayColumnMapping:
    def test_should_map_portuguese_column_titles(self) -> None:
        assert resolve_field_for_column("CPF") == "consumer_cpf"
        assert resolve_field_for_column("Número CIP/FA") == "protocol_number"
        assert resolve_field_for_column("Link PDF Drive") == "pdf_url"
        assert resolve_field_for_column("Notificação Procon") == "pdf_url"
        assert resolve_field_for_column("Procon/Órgão") == "state"
        assert resolve_field_for_column("Origem") == "origin"
        assert resolve_field_for_column("Prazo resposta SAC") == "sac_deadline"
        assert resolve_field_for_column("Prazo Resposta Jurídico") == "legal_deadline"
        assert resolve_field_for_column("Prazo SAC") == "sac_deadline"
        assert resolve_field_for_column("Prazo Jurídico") == "legal_deadline"

    def test_should_ignore_causa_2_column(self) -> None:
        assert resolve_field_for_column("Causa 2") is None
        assert resolve_field_for_column("Causa 1") == "cause"

    def test_should_map_administrative_process_columns(self) -> None:
        assert resolve_field_for_column("Gerou Processo Administrativo") == FIELD_PA_GENERATED
        assert (
            resolve_field_for_column("Processo Administrativo Respondido") == FIELD_PA_RESPONDED
        )
        assert (
            resolve_field_for_column("Prazo Resposta Processo Administrativo")
            == FIELD_PA_DEADLINE
        )
        assert resolve_field_for_column("Número Processo Administrativo") == FIELD_PA_NUMBER

    def test_should_build_administrative_process_column_values(self) -> None:
        columns = [
            MondayColumn(
                id="status_pa",
                title="Gerou Processo Administrativo",
                column_type="status",
            ),
            MondayColumn(
                id="status_pa_resp",
                title="Processo Administrativo Respondido",
                column_type="status",
            ),
            MondayColumn(
                id="date_pa",
                title="Prazo Resposta Processo Administrativo",
                column_type="date",
            ),
            MondayColumn(id="text_pa", title="Número Processo Administrativo", column_type="text"),
        ]
        values = build_administrative_process_column_values(
            columns,
            administrative_process_number="35.001.003.26.1620383",
            pa_response_deadline=date(2026, 7, 25),
            pa_generated_label="Sim",
            pa_responded_label="Não",
        )
        assert values["status_pa"] == {"label": "Sim"}
        assert values["status_pa_resp"] == {"label": "Não"}
        assert values["date_pa"] == {"date": "2026-07-25"}
        assert values["text_pa"] == "35.001.003.26.1620383"

    def test_should_map_laura_cause_to_cancelamento_label(self) -> None:
        cause = (
            "Demais ServiçosServiços de Beleza e Cuidados PessoaisContrato / Oferta"
            "Dificuldade para alterar ou cancelar o contrato /serviço"
        )
        assert map_procon_cause_to_monday_status_label(cause) == "Problemas com Cancelamento"

    def test_should_map_cobranca_indevida_to_pagamento_label(self) -> None:
        assert (
            map_procon_cause_to_monday_status_label("Cobrança indevida")
            == "Problemas no pagamento"
        )

    def test_should_map_classification_with_details_to_cancelamento_label(self) -> None:
        cause = "Demais Serviços Dificuldade para cancelar a assinatura glam"
        assert map_procon_cause_to_monday_status_label(cause) == "Problemas com Cancelamento"

    def test_should_map_vicio_do_produto_to_experiencia_label(self) -> None:
        assert (
            map_procon_cause_to_monday_status_label("Vício do produto")
            == "Problemas na experiência"
        )

    def test_should_map_glam_subscription_cause_to_glam_clube_origin(self) -> None:
        cause = (
            "Demais ServiçosServiços de Beleza e Cuidados PessoaisContrato / Oferta"
            "Dificuldade para alterar ou cancelar o contrato /serviço"
        )
        assert map_complaint_to_origin_label(cause) == ORIGIN_LABEL_GLAM_CLUBE

    def test_should_map_glam_purchase_cause_to_glam_loja_origin(self) -> None:
        cause = (
            "Demais ProdutosArtigos de Uso PessoalEntrega do Produto"
            "Atraso na entrega do produto"
        )
        assert map_complaint_to_origin_label(cause) == ORIGIN_LABEL_GLAM_LOJA

    def test_should_map_mens_subscription_cause_to_mens_clube_origin(self) -> None:
        cause = "Men's Club assinatura cancelamento renovacao automatica"
        assert map_complaint_to_origin_label(cause) == ORIGIN_LABEL_MENS_CLUBE

    def test_should_map_mens_purchase_cause_to_mens_loja_origin(self) -> None:
        cause = "Men's loja compra pedido entrega produto"
        assert map_complaint_to_origin_label(cause) == ORIGIN_LABEL_MENS_LOJA

    def test_should_use_fallback_when_origin_cannot_be_inferred(self) -> None:
        assert (
            map_complaint_to_origin_label("", fallback=ORIGIN_LABEL_GLAM_CLUBE)
            == ORIGIN_LABEL_GLAM_CLUBE
        )
        assert (
            map_complaint_to_origin_label("problema generico", fallback=ORIGIN_LABEL_GLAM_LOJA)
            == ORIGIN_LABEL_GLAM_LOJA
        )

    def test_should_skip_unmapped_cause_on_status_column(self) -> None:
        columns = [
            MondayColumn(id="status_cause", title="Causa 1", column_type="status"),
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

    def test_should_fill_origin_and_deadline_columns(self) -> None:
        columns = [
            MondayColumn(id="status_origin", title="Origem", column_type="status"),
            MondayColumn(id="date_sac", title="Prazo resposta SAC", column_type="date"),
            MondayColumn(id="date_legal", title="Prazo Resposta Jurídico", column_type="date"),
            MondayColumn(id="link_pdf", title="Notificação Procon", column_type="link"),
        ]
        values = build_column_values(
            columns,
            consumer_name="GABRIELLE LIMA MARINO",
            state="SP",
            pdf_url="https://drive.google.com/file/d/abc/view",
            protocol_number="1663732/2026",
            consumer_cpf="49119340850",
            complaint_date=date(2026, 7, 17),
            sac_deadline=date(2026, 7, 22),
            legal_deadline=date(2026, 7, 23),
            cause="",
            origin_label='Glam "Clube"',
        )
        assert values["status_origin"] == {"label": 'Glam "Clube"'}
        assert values["date_sac"] == {"date": "2026-07-22"}
        assert values["date_legal"] == {"date": "2026-07-23"}
        assert values["link_pdf"] == {
            "url": "https://drive.google.com/file/d/abc/view",
            "text": "Notificação Procon",
        }

    def test_should_skip_file_column_for_notification_pdf(self) -> None:
        columns = [
            MondayColumn(id="file_pdf", title="Notificação Procon", column_type="file"),
        ]
        values = build_column_values(
            columns,
            consumer_name="GABRIELLE",
            state="SP",
            pdf_url="https://drive.google.com/file/d/abc/view",
            protocol_number="1663732/2026",
            consumer_cpf="49119340850",
            complaint_date=None,
            sac_deadline=None,
            legal_deadline=None,
            cause="",
            origin_label='Glam "Clube"',
        )
        assert values == {}

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

    def test_should_drop_invalid_status_labels(self) -> None:
        details = [
            MondayColumnDetails(
                column=MondayColumn(id="status_org", title="Procon/Órgão", column_type="status"),
                settings_str='{"labels": {"0": "SP", "1": "MS"}}',
            ),
            MondayColumnDetails(
                column=MondayColumn(id="text_cpf", title="CPF", column_type="text"),
            ),
        ]
        values = {
            "status_org": {"label": "RJ"},
            "text_cpf": "12345678901",
        }

        sanitized = sanitize_column_values(details, values)

        assert sanitized == {"text_cpf": "12345678901"}

    def test_should_parse_allowed_labels_from_settings(self) -> None:
        labels = allowed_labels('{"labels": {"0": "Problemas com entrega"}}', "status")
        assert labels == {"problemas com entrega"}
