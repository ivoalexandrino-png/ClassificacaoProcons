"""Testes da engrenagem entre quadros (casos, conexões, Status/Decisão e KPI)."""

from datetime import date
from unittest.mock import patch

import pytest

from classificacao_procons.juridico import casos
from classificacao_procons.juridico.casos import (
    CaseRef,
    create_case_for_citacao,
    find_case_item,
    is_trabalhista,
    link_item_to_case,
    sync_case_boards,
    update_case_for_stage,
    update_kpi_for_stage,
)
from classificacao_procons.juridico.models import (
    ACTION_CONTESTAR,
    ACTION_CUMPRIR_ACORDO,
    NOTIFICATION_TYPE_CITACAO,
    NOTIFICATION_TYPE_INTIMACAO,
    ParsedIntimacao,
    Providencia,
)
from classificacao_procons.juridico.providencias import STAGE_ACORDO, STAGE_ENCERRAMENTO

PROCESSOS_BOARD = {
    "columns": [
        {"id": "status2", "title": "Status", "type": "status",
         "settings_str": '{"labels": {"1": "Encerrado", "2": "Em Andamento", "5": "Suspenso"}}'},
        {"id": "status_10__1", "title": "Decisão Judicial", "type": "status",
         "settings_str": '{"labels": {"0": "Acordo", "2": "Condenação B4A/MMKT"}}'},
        {"id": "n_mero", "title": "Número", "type": "long_text", "settings_str": None},
        {"id": "tipo", "title": "Tipo de Ação", "type": "text", "settings_str": None},
    ],
    "groups": [
        {"id": "topics", "title": "Processos Consumidores Ativos"},
        {"id": "novo_grupo", "title": "Processos Encerrados"},
    ],
}

KPI_BOARD = {
    "columns": [
        {"id": "texto_longo", "title": "Número do Processo", "type": "long_text",
         "settings_str": None},
        {"id": "status_11", "title": "Resultado", "type": "status",
         "settings_str": '{"labels": {"0": "Em andamento", "2": "Condenação", "5": "Acordo"}}'},
        {"id": "status_160", "title": "Situação", "type": "status",
         "settings_str": '{"labels": {"0": "Arquivado", "1": "Ativo"}}'},
        {"id": "data_decisao", "title": "Data da Decisão", "type": "date",
         "settings_str": None},
    ],
    "groups": [{"id": "topics", "title": "2023"}],
}

INTIMACAO_CITACAO = ParsedIntimacao(
    process_number="1001234-83.2026.8.26.0100",
    notification_type=NOTIFICATION_TYPE_CITACAO,
    tribunal="TJSP",
    summary="Citação.",
)


class TestIsTrabalhista:
    def test_should_detect_trabalhista_by_segment_digit(self) -> None:
        assert is_trabalhista("1000817-79.2026.5.02.0511") is True

    def test_should_return_false_for_common_justice(self) -> None:
        assert is_trabalhista("1001234-83.2026.8.26.0100") is False

    def test_should_return_false_for_malformed_number(self) -> None:
        assert is_trabalhista("123") is False


class TestFindCaseItem:
    def test_should_find_case_in_processos_judiciais_board(self) -> None:
        with (
            patch.object(casos, "_board_id_from_env_or_name", side_effect=["555", None]),
            patch.object(casos, "_board_columns_with_settings", return_value=PROCESSOS_BOARD),
            patch.object(
                casos,
                "_search_case_in_board",
                return_value={"id": "901", "name": "Fulana de Tal"},
            ) as search,
        ):
            case = find_case_item("1001234-83.2026.8.26.0100", api_token="token")

        assert case is not None
        assert case.item_id == "901"
        assert case.board_id == "555"
        assert case.source == "judicial"
        assert search.call_args.kwargs["cnj_column_id"] == "n_mero"

    def test_should_return_none_when_case_not_found(self) -> None:
        with (
            patch.object(casos, "_board_id_from_env_or_name", side_effect=["555", "666"]),
            patch.object(casos, "_board_columns_with_settings", return_value=PROCESSOS_BOARD),
            patch.object(casos, "_search_case_in_board", return_value=None),
        ):
            assert find_case_item("1001234-83.2026.8.26.0100", api_token="token") is None

    def test_should_return_none_without_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MONDAY_API_TOKEN", raising=False)
        assert find_case_item("1001234-83.2026.8.26.0100") is None


class TestCreateCaseForCitacao:
    def test_should_create_case_in_active_consumers_group(self) -> None:
        with (
            patch.object(casos, "_board_id_from_env_or_name", return_value="555"),
            patch.object(casos, "_board_columns_with_settings", return_value=PROCESSOS_BOARD),
            patch.object(casos, "_create_item", return_value="902") as create_item,
            patch.object(casos, "_graphql_request") as gql,
        ):
            case = create_case_for_citacao(INTIMACAO_CITACAO, api_token="token")

        assert case is not None
        assert case.created is True
        assert case.item_id == "902"
        assert create_item.call_args.kwargs["group_id"] == "topics"
        # número CNJ escrito na coluna "Número" (long_text)
        variables = gql.call_args.kwargs["variables"]
        assert "n_mero" in variables["columnValues"]
        assert "1001234-83.2026.8.26.0100" in variables["columnValues"]

    def test_should_not_create_case_for_trabalhista(self) -> None:
        intimacao = ParsedIntimacao(
            process_number="1000817-79.2026.5.02.0511",
            notification_type=NOTIFICATION_TYPE_CITACAO,
        )
        assert create_case_for_citacao(intimacao, api_token="token") is None


class TestLinkItemToCase:
    def test_should_link_via_board_relation_column(self) -> None:
        board = {
            "columns": [
                {"id": "conectar_quadros", "title": "Processos Consumidores",
                 "type": "board_relation", "settings_str": '{"boardIds": [555]}'},
            ],
            "groups": [],
        }
        case = CaseRef(board_id="555", item_id="901", item_name="Fulana", source="judicial")
        with (
            patch.object(casos, "_board_columns_with_settings", return_value=board),
            patch.object(casos, "_graphql_request") as gql,
        ):
            linked = link_item_to_case(
                api_token="token", board_id="123", item_id="777", case=case,
            )

        assert linked is True
        variables = gql.call_args.kwargs["variables"]
        assert '"item_ids": [901]' in variables["columnValues"]

    def test_should_return_false_when_no_relation_column_points_to_board(self) -> None:
        board = {"columns": [], "groups": []}
        case = CaseRef(board_id="555", item_id="901", item_name="Fulana", source="judicial")
        with patch.object(casos, "_board_columns_with_settings", return_value=board):
            assert (
                link_item_to_case(api_token="token", board_id="123", item_id="777", case=case)
                is False
            )


class TestUpdateCaseForStage:
    def test_should_set_status_encerrado_on_encerramento(self) -> None:
        case = CaseRef(board_id="555", item_id="901", item_name="Fulana", source="judicial")
        with (
            patch.object(casos, "_board_columns_with_settings", return_value=PROCESSOS_BOARD),
            patch.object(casos, "_graphql_request") as gql,
        ):
            applied = update_case_for_stage(case, api_token="token", stage=STAGE_ENCERRAMENTO)

        assert applied == ["caso: Status=Encerrado"]
        assert '"Encerrado"' in gql.call_args.kwargs["variables"]["columnValues"]

    def test_should_set_decisao_acordo_on_acordo(self) -> None:
        case = CaseRef(board_id="555", item_id="901", item_name="Fulana", source="judicial")
        with (
            patch.object(casos, "_board_columns_with_settings", return_value=PROCESSOS_BOARD),
            patch.object(casos, "_graphql_request"),
        ):
            applied = update_case_for_stage(case, api_token="token", stage=STAGE_ACORDO)

        assert applied == ["caso: Decisão Judicial=Acordo"]

    def test_should_not_write_when_label_does_not_exist(self) -> None:
        board = {
            "columns": [
                {"id": "status2", "title": "Status", "type": "status",
                 "settings_str": '{"labels": {"2": "Em Andamento"}}'},
            ],
            "groups": [],
        }
        case = CaseRef(board_id="555", item_id="901", item_name="Fulana", source="judicial")
        with (
            patch.object(casos, "_board_columns_with_settings", return_value=board),
            patch.object(casos, "_graphql_request") as gql,
        ):
            applied = update_case_for_stage(case, api_token="token", stage=STAGE_ENCERRAMENTO)

        assert applied == []
        gql.assert_not_called()


class TestUpdateKpiForStage:
    def test_should_set_resultado_acordo_and_decision_date(self) -> None:
        with (
            patch.object(casos, "_board_id_from_env_or_name", return_value="777"),
            patch.object(casos, "_board_columns_with_settings", return_value=KPI_BOARD),
            patch.object(
                casos,
                "_search_case_in_board",
                return_value={"id": "333", "name": "Fulana"},
            ),
            patch.object(casos, "_graphql_request") as gql,
        ):
            applied = update_kpi_for_stage(
                "1001234-83.2026.8.26.0100",
                api_token="token",
                stage=STAGE_ACORDO,
                decision_date=date(2026, 6, 20),
            )

        assert applied == ["kpi: Resultado=Acordo", "kpi: Data da Decisão"]
        assert gql.call_count == 2

    def test_should_set_situacao_arquivado_on_encerramento(self) -> None:
        with (
            patch.object(casos, "_board_id_from_env_or_name", return_value="777"),
            patch.object(casos, "_board_columns_with_settings", return_value=KPI_BOARD),
            patch.object(
                casos,
                "_search_case_in_board",
                return_value={"id": "333", "name": "Fulana"},
            ),
            patch.object(casos, "_graphql_request"),
        ):
            applied = update_kpi_for_stage(
                "1001234-83.2026.8.26.0100",
                api_token="token",
                stage=STAGE_ENCERRAMENTO,
                decision_date=None,
            )

        assert applied == ["kpi: Situação=Arquivado"]

    def test_should_not_create_kpi_row_when_process_is_missing(self) -> None:
        with (
            patch.object(casos, "_board_id_from_env_or_name", return_value="777"),
            patch.object(casos, "_board_columns_with_settings", return_value=KPI_BOARD),
            patch.object(casos, "_search_case_in_board", return_value=None),
            patch.object(casos, "_graphql_request") as gql,
        ):
            applied = update_kpi_for_stage(
                "1001234-83.2026.8.26.0100",
                api_token="token",
                stage=STAGE_ACORDO,
                decision_date=None,
            )

        assert applied == []
        gql.assert_not_called()


class TestSyncCaseBoards:
    def _providencia(self) -> Providencia:
        return Providencia(
            action_type=ACTION_CUMPRIR_ACORDO,
            description="Acompanhar cumprimento do acordo homologado",
            requires_action=True,
        )

    def test_should_link_annotate_and_update_stage(self) -> None:
        case = CaseRef(board_id="555", item_id="901", item_name="Fulana", source="judicial")
        intimacao = ParsedIntimacao(
            process_number="1001234-83.2026.8.26.0100",
            notification_type=NOTIFICATION_TYPE_INTIMACAO,
        )
        with (
            patch.object(casos, "find_case_item", return_value=case),
            patch.object(casos, "link_item_to_case", return_value=True) as link,
            patch.object(casos, "_create_update") as create_update,
            patch.object(
                casos, "update_case_for_stage", return_value=["caso: Decisão Judicial=Acordo"],
            ),
            patch.object(casos, "update_kpi_for_stage", return_value=["kpi: Resultado=Acordo"]),
        ):
            result = sync_case_boards(
                intimacao=intimacao,
                providencia=self._providencia(),
                analysis="Parecer.",
                stage=STAGE_ACORDO,
                stage_marker_date=date(2026, 6, 20),
                prazo_board_id="123",
                prazo_item_id="777",
                audiencia_board_id=None,
                audiencia_item_id=None,
                api_token="token",
            )

        assert result.case == case
        assert "item de prazo conectado ao caso" in result.actions
        assert "movimentação anotada no caso" in result.actions
        assert "caso: Decisão Judicial=Acordo" in result.actions
        assert "kpi: Resultado=Acordo" in result.actions
        assert result.errors == []
        link.assert_called_once()
        create_update.assert_called_once()

    def test_should_create_case_when_citacao_has_no_case(self) -> None:
        created = CaseRef(
            board_id="555", item_id="902", item_name="Novo processo", source="judicial",
            created=True,
        )
        with (
            patch.object(casos, "find_case_item", return_value=None),
            patch.object(casos, "create_case_for_citacao", return_value=created) as create,
            patch.object(casos, "link_item_to_case", return_value=True),
            patch.object(casos, "_create_update"),
        ):
            result = sync_case_boards(
                intimacao=INTIMACAO_CITACAO,
                providencia=self._providencia(),
                analysis=None,
                stage=None,
                stage_marker_date=None,
                prazo_board_id=None,
                prazo_item_id=None,
                audiencia_board_id=None,
                audiencia_item_id=None,
                api_token="token",
            )

        create.assert_called_once()
        assert result.case == created
        assert "caso criado no quadro Processos Judiciais" in result.actions

    def test_should_report_missing_case_without_creating_for_intimacao(self) -> None:
        intimacao = ParsedIntimacao(
            process_number="1001234-83.2026.8.26.0100",
            notification_type=NOTIFICATION_TYPE_INTIMACAO,
        )
        with (
            patch.object(casos, "find_case_item", return_value=None),
            patch.object(casos, "create_case_for_citacao") as create,
        ):
            result = sync_case_boards(
                intimacao=intimacao,
                providencia=self._providencia(),
                analysis=None,
                stage=None,
                stage_marker_date=None,
                prazo_board_id=None,
                prazo_item_id=None,
                audiencia_board_id=None,
                audiencia_item_id=None,
                api_token="token",
            )

        create.assert_not_called()
        assert result.case is None
        assert result.note() == "caso não encontrado no quadro-mestre"

    def test_should_not_update_kpi_for_trabalhista_case(self) -> None:
        case = CaseRef(board_id="666", item_id="903", item_name="RT", source="trabalhista")
        intimacao = ParsedIntimacao(
            process_number="1000817-79.2026.5.02.0511",
            notification_type=NOTIFICATION_TYPE_INTIMACAO,
        )
        with (
            patch.object(casos, "find_case_item", return_value=case),
            patch.object(casos, "_create_update"),
            patch.object(casos, "update_case_for_stage", return_value=[]),
            patch.object(casos, "update_kpi_for_stage") as kpi,
        ):
            sync_case_boards(
                intimacao=intimacao,
                providencia=self._providencia(),
                analysis=None,
                stage=STAGE_ACORDO,
                stage_marker_date=None,
                prazo_board_id=None,
                prazo_item_id=None,
                audiencia_board_id=None,
                audiencia_item_id=None,
                api_token="token",
            )

        kpi.assert_not_called()

    def test_should_use_contestar_providencia(self) -> None:
        # sanity: providência de citação também passa pela engrenagem
        case = CaseRef(board_id="555", item_id="901", item_name="Fulana", source="judicial")
        providencia = Providencia(
            action_type=ACTION_CONTESTAR,
            description="Apresentar contestação",
            requires_action=True,
        )
        with (
            patch.object(casos, "find_case_item", return_value=case),
            patch.object(casos, "link_item_to_case", return_value=True),
            patch.object(casos, "_create_update") as create_update,
        ):
            result = sync_case_boards(
                intimacao=INTIMACAO_CITACAO,
                providencia=providencia,
                analysis="Análise.",
                stage=None,
                stage_marker_date=None,
                prazo_board_id="123",
                prazo_item_id="777",
                audiencia_board_id=None,
                audiencia_item_id=None,
                api_token="token",
            )

        assert "Apresentar contestação" in create_update.call_args.kwargs["body"]
        assert result.errors == []
