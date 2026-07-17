"""Testes do mapeamento de colunas do board jurídico."""

from datetime import date, datetime

from classificacao_procons.juridico.mapping import (
    FIELD_AUDIENCIA,
    FIELD_PRAZO_FINAL,
    FIELD_PROCESSO,
    FIELD_STATUS,
    build_providencia_column_values,
    find_column_by_field,
    resolve_field_for_column,
)
from classificacao_procons.monday.mapping import MondayColumn


def _columns() -> list[MondayColumn]:
    return [
        MondayColumn(id="c_proc", title="Número do Processo", column_type="text"),
        MondayColumn(id="c_trib", title="Tribunal", column_type="text"),
        MondayColumn(id="c_vara", title="Vara/Juízo", column_type="text"),
        MondayColumn(id="c_prazo", title="Prazo Final", column_type="date"),
        MondayColumn(id="c_aud", title="Audiência", column_type="date"),
        MondayColumn(id="c_prov", title="Providência", column_type="text"),
        MondayColumn(id="c_status", title="Status", column_type="text"),
        MondayColumn(id="c_link", title="Link do Andamento", column_type="link"),
    ]


class TestResolveField:
    def test_should_resolve_process_column(self) -> None:
        assert resolve_field_for_column("Número do Processo") == FIELD_PROCESSO

    def test_should_resolve_prazo_before_generic(self) -> None:
        assert resolve_field_for_column("Prazo Final") == FIELD_PRAZO_FINAL

    def test_should_resolve_audiencia(self) -> None:
        assert resolve_field_for_column("Data da Audiência") == FIELD_AUDIENCIA

    def test_should_return_none_for_unknown(self) -> None:
        assert resolve_field_for_column("Coluna Aleatória") is None


class TestFindColumnByField:
    def test_should_find_status_column(self) -> None:
        column = find_column_by_field(_columns(), FIELD_STATUS)
        assert column is not None
        assert column.id == "c_status"


class TestBuildColumnValues:
    def test_should_build_expected_values(self) -> None:
        values = build_providencia_column_values(
            _columns(),
            process_number="1023456-78.2026.8.26.0100",
            tribunal="TJSP",
            vara="3ª Vara Cível",
            tipo="Contestar",
            providencia="Contestar — TJSP",
            prazo_final=date(2026, 8, 7),
            hearing_at=None,
            status="A providenciar",
            partes=None,
            link="https://esaj.tjsp.jus.br/x",
        )
        assert values["c_proc"] == "1023456-78.2026.8.26.0100"
        assert values["c_prazo"] == {"date": "2026-08-07"}
        assert values["c_link"] == {"url": "https://esaj.tjsp.jus.br/x", "text": "Andamento"}
        assert "c_aud" not in values  # sem audiência

    def test_should_format_hearing_datetime_for_date_column(self) -> None:
        values = build_providencia_column_values(
            _columns(),
            process_number="1023456-78.2026.8.26.0100",
            tribunal="TJSP",
            vara=None,
            tipo="Audiência",
            providencia="Audiência",
            prazo_final=None,
            hearing_at=datetime(2026, 8, 15, 14, 30),
            status="A providenciar",
            partes=None,
            link=None,
        )
        assert values["c_aud"] == {"date": "2026-08-15", "time": "14:30"}
