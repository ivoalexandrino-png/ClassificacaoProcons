"""Testes do mapeamento Monday para resposta."""

from classificacao_procons.monday.mapping import (
    FIELD_DOCS_SAC,
    FIELD_STATUS,
    parse_link_column_value,
    parse_status_text,
    resolve_field_for_column,
)


class TestMondayResponseMapping:
    def test_should_map_docs_sac_and_status_columns(self) -> None:
        assert resolve_field_for_column("Docs SAC") == FIELD_DOCS_SAC
        assert resolve_field_for_column("Status") == FIELD_STATUS
        assert resolve_field_for_column("Data da Resposta Legal/Baixa") == "response_date"
        assert resolve_field_for_column("Prazo Jurídico") == "legal_deadline"

    def test_should_parse_link_column_value(self) -> None:
        raw = '{"url":"https://drive.google.com/drive/folders/abc123","text":"Docs"}'
        assert parse_link_column_value(raw) == "https://drive.google.com/drive/folders/abc123"

    def test_should_parse_status_text(self) -> None:
        assert parse_status_text(" Pendente ") == "Pendente"
