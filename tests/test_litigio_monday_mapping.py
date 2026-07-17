"""Testes do mapeamento de colunas do board de Litígio."""

from datetime import date

from classificacao_procons.litigio.models import EventoProcesso, ProvidenciaTipo
from classificacao_procons.litigio.monday_mapping import (
    build_column_values,
    find_processo_column,
    resolve_field_for_column,
)
from classificacao_procons.monday.mapping import MondayColumn


def _evento(**overrides: object) -> EventoProcesso:
    defaults: dict[str, object] = {
        "numero_processo": "00000012320268260100",
        "numero_processo_formatado": "0000001-23.2026.8.26.0100",
        "tribunal": "TJSP",
        "tipo_providencia": ProvidenciaTipo.AUDIENCIA,
        "descricao": "Audiência designada.",
        "requer_atencao": True,
        "intimacao_id": 1,
        "data_disponibilizacao": date(2026, 7, 11),
        "prazo_data": None,
        "data_audiencia": date(2026, 8, 20),
        "certidao_url": "https://comunicaapi.pje.jus.br/api/v1/comunicacao/hash-1/certidao",
        "link_tribunal": None,
    }
    defaults.update(overrides)
    return EventoProcesso(**defaults)  # type: ignore[arg-type]


class TestResolveFieldForColumn:
    def test_should_resolve_processo_column_by_keyword(self) -> None:
        assert resolve_field_for_column("Número do Processo") == "numero_processo"

    def test_should_return_none_when_title_has_no_known_keyword(self) -> None:
        assert resolve_field_for_column("Observações internas irrelevantes XYZ") is None


class TestFindProcessoColumn:
    def test_should_find_column_by_processo_field(self) -> None:
        columns = [
            MondayColumn(id="c1", title="Tribunal", column_type="text"),
            MondayColumn(id="c2", title="CNJ", column_type="text"),
        ]
        column = find_processo_column(columns)
        assert column is not None
        assert column.id == "c2"

    def test_should_return_none_when_no_column_matches(self) -> None:
        columns = [MondayColumn(id="c1", title="Observações", column_type="text")]
        assert find_processo_column(columns) is None


class TestBuildColumnValues:
    def test_should_format_status_and_date_columns(self) -> None:
        columns = [
            MondayColumn(id="c_providencia", title="Providência", column_type="status"),
            MondayColumn(id="c_audiencia", title="Data Audiência", column_type="date"),
            MondayColumn(id="c_prazo", title="Prazo", column_type="date"),
        ]
        values = build_column_values(columns, _evento())

        assert values["c_providencia"] == {"label": "Audiência agendada"}
        assert values["c_audiencia"] == {"date": "2026-08-20"}
        assert "c_prazo" not in values  # prazo_data é None neste evento

    def test_should_format_link_columns_with_text(self) -> None:
        columns = [MondayColumn(id="c_link", title="Link Certidão", column_type="link")]
        values = build_column_values(columns, _evento())

        assert values["c_link"]["url"] == _evento().certidao_url
        assert values["c_link"]["text"] == "Certidão DJEN"

    def test_should_skip_columns_without_known_field(self) -> None:
        columns = [MondayColumn(id="c1", title="Comentário livre", column_type="text")]
        values = build_column_values(columns, _evento())
        assert values == {}
