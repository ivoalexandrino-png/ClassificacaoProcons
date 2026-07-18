"""Testes do cadastro de providências no Monday (mapeamento e registro)."""

from datetime import date, datetime
from unittest.mock import patch

import pytest

from classificacao_procons.juridico import monday as juridico_monday
from classificacao_procons.juridico.models import (
    ACTION_ANALISAR_RECURSO,
    ACTION_COMPARECER_AUDIENCIA,
    ACTION_CONTESTAR,
    NOTIFICATION_TYPE_AUDIENCIA,
    NOTIFICATION_TYPE_CITACAO,
    ParsedIntimacao,
    Providencia,
)
from classificacao_procons.juridico.monday import (
    _pick_juridico_board,
    build_providencia_column_values,
    register_audiencia,
    register_providencia,
    resolve_juridico_field_for_column,
)
from classificacao_procons.monday.client import MondayBoardContext
from classificacao_procons.monday.mapping import MondayColumn, MondayColumnDetails

BOARD_COLUMNS = [
    MondayColumn(id="col_id", title="ID Intimação", column_type="text"),
    MondayColumn(id="col_proc", title="Nº do Processo", column_type="text"),
    MondayColumn(id="col_trib", title="Tribunal", column_type="text"),
    MondayColumn(id="col_vara", title="Vara / Comarca", column_type="text"),
    MondayColumn(id="col_tipo", title="Tipo de Intimação", column_type="status"),
    MondayColumn(id="col_prov", title="Providência", column_type="text"),
    MondayColumn(id="col_prazo", title="Prazo Fatal", column_type="date"),
    MondayColumn(id="col_aud", title="Audiência", column_type="date"),
    MondayColumn(id="col_teor", title="Teor da Intimação", column_type="long_text"),
    MondayColumn(id="col_analise", title="Análise do Caso", column_type="long_text"),
]

INTIMACAO = ParsedIntimacao(
    process_number="1001234-56.2026.8.26.0100",
    notification_type=NOTIFICATION_TYPE_CITACAO,
    tribunal="TJSP",
    court_unit="1a Vara Civel de Sao Paulo",
    summary="Citação para contestar em 15 dias úteis.",
)

PROVIDENCIA = Providencia(
    action_type=ACTION_CONTESTAR,
    description="Apresentar contestação",
    requires_action=True,
    due_date=date(2026, 8, 7),
    requires_legal_document=True,
)


class TestResolveJuridicoFieldForColumn:
    def test_should_resolve_process_number_column(self) -> None:
        assert resolve_juridico_field_for_column("Nº do Processo") == "process_number"

    def test_should_resolve_prazo_fatal_before_generic_prazo(self) -> None:
        assert resolve_juridico_field_for_column("Prazo Fatal") == "due_date"

    def test_should_resolve_fatal_column_from_real_board(self) -> None:
        # Título real da coluna de prazo no quadro "prazos"
        assert resolve_juridico_field_for_column("Fatal") == "due_date"

    def test_should_resolve_audiencia_column(self) -> None:
        assert resolve_juridico_field_for_column("Audiência") == "hearing_datetime"

    def test_should_resolve_intimacao_id_column(self) -> None:
        assert resolve_juridico_field_for_column("ID Intimação") == "intimacao_id"

    def test_should_resolve_analysis_column(self) -> None:
        assert resolve_juridico_field_for_column("Análise do Caso") == "analysis"

    def test_should_resolve_numero_processo_without_do(self) -> None:
        # Título real do quadro "prazos"
        assert resolve_juridico_field_for_column("Número Processo") == "process_number"

    def test_should_not_map_procon_or_other_domain_columns_to_process_number(self) -> None:
        # Títulos reais dos quadros de legal — pertencem a outros domínios
        assert resolve_juridico_field_for_column("Processo Administrativo") is None
        assert resolve_juridico_field_for_column("Processos Consumidores") is None

    def test_should_never_map_responsavel_columns(self) -> None:
        # Coluna real do quadro "audiências" — atribuição manual de pessoa
        assert resolve_juridico_field_for_column("Responsável por comparecer") is None

    def test_should_return_none_for_unrelated_column(self) -> None:
        assert resolve_juridico_field_for_column("Responsável interno") is None


class TestBuildProvidenciaColumnValues:
    def test_should_fill_all_mapped_columns(self) -> None:
        values = build_providencia_column_values(
            BOARD_COLUMNS,
            intimacao=INTIMACAO,
            providencia=PROVIDENCIA,
            message_id="msg-001",
            analysis="O que aconteceu: citação recebida; contestar até 07/08.",
        )

        assert values["col_id"] == "msg-001"
        assert values["col_proc"] == "1001234-56.2026.8.26.0100"
        assert values["col_trib"] == "TJSP"
        assert values["col_vara"] == "1a Vara Civel de Sao Paulo"
        assert values["col_tipo"] == {"label": "Citação"}
        assert values["col_prov"] == "Apresentar contestação"
        assert values["col_prazo"] == {"date": "2026-08-07"}
        assert values["col_teor"] == {"text": "Citação para contestar em 15 dias úteis."}
        assert values["col_analise"] == {
            "text": "O que aconteceu: citação recebida; contestar até 07/08.",
        }
        assert "col_aud" not in values

    def test_should_fill_hearing_with_date_and_time(self) -> None:
        providencia = Providencia(
            action_type=ACTION_COMPARECER_AUDIENCIA,
            description="Preparar e comparecer à audiência",
            requires_action=True,
            hearing_datetime=datetime(2026, 8, 5, 14, 30),
        )
        intimacao = ParsedIntimacao(
            process_number="1001234-56.2026.8.26.0100",
            notification_type=NOTIFICATION_TYPE_AUDIENCIA,
        )

        values = build_providencia_column_values(
            BOARD_COLUMNS,
            intimacao=intimacao,
            providencia=providencia,
            message_id="msg-002",
        )
        assert values["col_aud"] == {"date": "2026-08-05", "time": "14:30:00"}

    def test_should_not_write_hearing_into_non_date_columns(self) -> None:
        """"Link Audiência"/"Orientações de Audiência" (quadro real) ficam manuais."""
        columns = BOARD_COLUMNS + [
            MondayColumn(id="col_link_aud", title="Link Audiência", column_type="link"),
            MondayColumn(
                id="col_orient",
                title="Orientações de Audiência",
                column_type="long_text",
            ),
        ]
        providencia = Providencia(
            action_type=ACTION_COMPARECER_AUDIENCIA,
            description="Preparar e comparecer à audiência",
            requires_action=True,
            hearing_datetime=datetime(2026, 8, 5, 14, 30),
        )
        values = build_providencia_column_values(
            columns,
            intimacao=INTIMACAO,
            providencia=providencia,
            message_id="msg-005",
        )
        assert values["col_aud"] == {"date": "2026-08-05", "time": "14:30:00"}
        assert "col_link_aud" not in values
        assert "col_orient" not in values

    def test_should_omit_time_when_hearing_has_no_time(self) -> None:
        providencia = Providencia(
            action_type=ACTION_COMPARECER_AUDIENCIA,
            description="Preparar e comparecer à audiência",
            requires_action=True,
            hearing_datetime=datetime(2026, 8, 5),
        )
        values = build_providencia_column_values(
            BOARD_COLUMNS,
            intimacao=INTIMACAO,
            providencia=providencia,
            message_id="msg-003",
        )
        assert values["col_aud"] == {"date": "2026-08-05"}

    def test_should_skip_empty_fields(self) -> None:
        intimacao = ParsedIntimacao(
            process_number="1001234-56.2026.8.26.0100",
            notification_type=NOTIFICATION_TYPE_CITACAO,
        )
        values = build_providencia_column_values(
            BOARD_COLUMNS,
            intimacao=intimacao,
            providencia=PROVIDENCIA,
            message_id="msg-004",
        )
        assert "col_trib" not in values
        assert "col_vara" not in values


def _board_context(columns: list[MondayColumn] | None = None) -> MondayBoardContext:
    board_columns = columns if columns is not None else BOARD_COLUMNS
    return MondayBoardContext(
        board_id="123",
        group_id="grp",
        columns=board_columns,
        column_details=[MondayColumnDetails(column=column) for column in board_columns],
        account_slug="empresa",
    )


# Colunas do quadro "Prazos" real: sem "ID Intimação" e sem coluna de análise.
REAL_PRAZOS_COLUMNS = [
    MondayColumn(id="col_proc", title="Número Processo", column_type="text"),
    MondayColumn(id="col_data", title="Data", column_type="date"),
    MondayColumn(id="col_fatal", title="Fatal", column_type="date"),
]


class TestPickJuridicoBoard:
    def test_should_match_board_by_exact_normalized_name(self) -> None:
        boards = [{"id": "1", "name": "Prazos"}, {"id": "2", "name": "Audiências"}]
        found = _pick_juridico_board(boards, "prazos")
        assert found is not None
        assert found["id"] == "1"

    def test_should_match_board_containing_target_name(self) -> None:
        boards = [{"id": "3", "name": "Processos Judiciais"}]
        found = _pick_juridico_board(boards, "processos judiciais")
        assert found is not None
        assert found["id"] == "3"

    def test_should_not_fall_back_to_unrelated_board(self) -> None:
        boards = [{"id": "9", "name": "procons"}]
        assert _pick_juridico_board(boards, "prazos") is None


class TestLoadJuridicoBoardContext:
    def test_should_fall_back_to_first_group_when_group_not_found(self) -> None:
        board = {
            "id": "77",
            "name": "Prazos",
            "groups": [{"id": "g1", "title": "Semana atual"}],
            "columns": [],
        }
        with (
            patch.object(juridico_monday, "_list_all_boards", return_value=[board]),
            patch.object(juridico_monday, "_account_slug", return_value="empresa"),
        ):
            context = juridico_monday._load_juridico_board_context(
                api_token="token-teste",
                board_name="prazos",
                board_id=None,
                group_name="grupo inexistente",
            )
        assert context.board_id == "77"
        assert context.group_id == "g1"

    def test_should_raise_with_visible_boards_when_board_not_found(self) -> None:
        boards = [{"id": "1", "name": "procons", "groups": [], "columns": []}]
        with (
            patch.object(juridico_monday, "_list_all_boards", return_value=boards),
            pytest.raises(juridico_monday.MondayClientError, match="procons"),
        ):
            juridico_monday._load_juridico_board_context(
                api_token="token-teste",
                board_name="prazos",
                board_id=None,
                group_name="",
            )


class TestFindExistingItemIdByName:
    def test_should_return_id_when_name_matches_exactly(self) -> None:
        response = {
            "boards": [
                {
                    "items_page": {
                        "items": [
                            {"id": "12", "name": "1001234-56.2026.8.26.0100 — Outra coisa"},
                            {
                                "id": "34",
                                "name": "1001234-56.2026.8.26.0100 — Apresentar contestação",
                            },
                        ],
                    },
                },
            ],
        }
        with patch.object(juridico_monday, "_graphql_request", return_value=response):
            found = juridico_monday._find_existing_item_id_by_name(
                api_token="token-teste",
                board_id="123",
                item_name="1001234-56.2026.8.26.0100 — Apresentar contestação",
            )
        assert found == "34"

    def test_should_return_none_when_only_partial_match_exists(self) -> None:
        response = {
            "boards": [
                {
                    "items_page": {
                        "items": [
                            {"id": "12", "name": "1001234-56.2026.8.26.0100 — Analisar recurso"},
                        ],
                    },
                },
            ],
        }
        with patch.object(juridico_monday, "_graphql_request", return_value=response):
            found = juridico_monday._find_existing_item_id_by_name(
                api_token="token-teste",
                board_id="123",
                item_name="1001234-56.2026.8.26.0100 — Apresentar contestação",
            )
        assert found is None

    def test_should_return_none_when_board_is_missing(self) -> None:
        with patch.object(juridico_monday, "_graphql_request", return_value={"boards": []}):
            found = juridico_monday._find_existing_item_id_by_name(
                api_token="token-teste",
                board_id="123",
                item_name="qualquer",
            )
        assert found is None


class TestRegisterProvidencia:
    def test_should_return_none_when_token_is_missing(
        self,
        monkeypatch,
    ) -> None:
        monkeypatch.delenv("MONDAY_API_TOKEN", raising=False)
        result = register_providencia(
            intimacao=INTIMACAO,
            providencia=PROVIDENCIA,
            message_id="msg-001",
        )
        assert result is None

    def test_should_create_item_with_column_values(self) -> None:
        with (
            patch.object(
                juridico_monday,
                "_load_juridico_board_context",
                return_value=_board_context(),
            ),
            patch.object(juridico_monday, "_find_existing_item_id", return_value=None),
            patch.object(juridico_monday, "_search_items_by_name", return_value=[]),
            patch.object(juridico_monday, "_create_item", return_value="777") as create_item,
            patch.object(juridico_monday, "_apply_complaint_column_values") as apply_values,
        ):
            result = register_providencia(
                intimacao=INTIMACAO,
                providencia=PROVIDENCIA,
                message_id="msg-001",
                api_token="token-teste",
            )

        assert result is not None
        assert result.item_id == "777"
        assert result.skipped_duplicate is False
        assert result.item_url == "https://empresa.monday.com/boards/123/pulses/777"
        assert create_item.call_args.kwargs["item_name"] == (
            "1001234-56.2026.8.26.0100 — Apresentar contestação"
        )
        applied = apply_values.call_args.kwargs["column_values"]
        assert applied["col_prazo"] == {"date": "2026-08-07"}

    def test_should_skip_duplicate_when_intimacao_already_registered(self) -> None:
        with (
            patch.object(
                juridico_monday,
                "_load_juridico_board_context",
                return_value=_board_context(),
            ),
            patch.object(juridico_monday, "_find_existing_item_id", return_value="555"),
            patch.object(juridico_monday, "_create_item") as create_item,
        ):
            result = register_providencia(
                intimacao=INTIMACAO,
                providencia=PROVIDENCIA,
                message_id="msg-001",
                api_token="token-teste",
            )

        assert result is not None
        assert result.skipped_duplicate is True
        assert result.item_id == "555"
        create_item.assert_not_called()

    def test_should_skip_duplicate_when_item_with_same_name_exists(self) -> None:
        """Dois e-mails distintos da mesma intimação não podem duplicar o item."""
        existing = [
            {"id": "999", "name": "1001234-56.2026.8.26.0100 — Apresentar contestação"},
        ]
        with (
            patch.object(
                juridico_monday,
                "_load_juridico_board_context",
                return_value=_board_context(),
            ),
            patch.object(juridico_monday, "_find_existing_item_id", return_value=None),
            patch.object(
                juridico_monday,
                "_search_items_by_name",
                return_value=existing,
            ) as search_items,
            patch.object(juridico_monday, "_create_update") as create_update,
            patch.object(juridico_monday, "_create_item") as create_item,
        ):
            result = register_providencia(
                intimacao=INTIMACAO,
                providencia=PROVIDENCIA,
                message_id="msg-outro-email",
                api_token="token-teste",
            )

        assert result is not None
        assert result.skipped_duplicate is True
        assert result.item_id == "999"
        create_item.assert_not_called()
        assert search_items.call_args.kwargs["name_contains"] == "1001234-56.2026.8.26.0100"
        note = create_update.call_args.kwargs["body"]
        assert "msg-outro-email" in note
        assert "Apresentar contestação" in note

    def test_should_skip_when_existing_item_has_later_stage_providencia(self) -> None:
        """Push atrasado de citação não recria prazo se o processo já está em recurso."""
        existing = [
            {
                "id": "1000",
                "name": "1001234-56.2026.8.26.0100 — Analisar sentença e avaliar recurso",
            },
        ]
        with (
            patch.object(
                juridico_monday,
                "_load_juridico_board_context",
                return_value=_board_context(),
            ),
            patch.object(juridico_monday, "_find_existing_item_id", return_value=None),
            patch.object(juridico_monday, "_search_items_by_name", return_value=existing),
            patch.object(juridico_monday, "_create_update") as create_update,
            patch.object(juridico_monday, "_create_item") as create_item,
        ):
            result = register_providencia(
                intimacao=INTIMACAO,
                providencia=PROVIDENCIA,
                message_id="msg-push-atrasado",
                api_token="token-teste",
            )

        assert result is not None
        assert result.skipped_duplicate is True
        assert result.item_id == "1000"
        create_item.assert_not_called()
        create_update.assert_called_once()

    def test_should_create_item_when_existing_providencia_is_earlier_stage(self) -> None:
        """Sentença nova cria item mesmo com prazo de contestação antigo no board."""
        existing = [
            {"id": "555", "name": "1001234-56.2026.8.26.0100 — Apresentar contestação"},
        ]
        providencia = Providencia(
            action_type=ACTION_ANALISAR_RECURSO,
            description="Analisar sentença e avaliar recurso",
            requires_action=True,
            due_date=date(2026, 9, 1),
            requires_legal_document=True,
        )
        with (
            patch.object(
                juridico_monday,
                "_load_juridico_board_context",
                return_value=_board_context(),
            ),
            patch.object(juridico_monday, "_find_existing_item_id", return_value=None),
            patch.object(juridico_monday, "_search_items_by_name", return_value=existing),
            patch.object(juridico_monday, "_create_update") as create_update,
            patch.object(juridico_monday, "_create_item", return_value="556") as create_item,
            patch.object(juridico_monday, "_apply_complaint_column_values"),
        ):
            result = register_providencia(
                intimacao=INTIMACAO,
                providencia=providencia,
                message_id="msg-sentenca",
                api_token="token-teste",
            )

        assert result is not None
        assert result.skipped_duplicate is False
        assert result.item_id == "556"
        create_item.assert_called_once()
        create_update.assert_not_called()

    def test_should_post_analysis_as_update_when_board_lacks_analysis_column(self) -> None:
        """O quadro real de prazos não tem coluna de análise: o andamento
        específico vai como update na timeline do item criado."""
        with (
            patch.object(
                juridico_monday,
                "_load_juridico_board_context",
                return_value=_board_context(REAL_PRAZOS_COLUMNS),
            ),
            patch.object(juridico_monday, "_search_items_by_name", return_value=[]),
            patch.object(juridico_monday, "_create_item", return_value="777"),
            patch.object(juridico_monday, "_apply_complaint_column_values"),
            patch.object(juridico_monday, "_create_update") as create_update,
        ):
            result = register_providencia(
                intimacao=INTIMACAO,
                providencia=PROVIDENCIA,
                message_id="msg-001",
                analysis="O DataJud mostra acordo homologado em 20/06/2026.",
                api_token="token-teste",
            )

        assert result is not None
        assert result.skipped_duplicate is False
        create_update.assert_called_once()
        assert create_update.call_args.kwargs["item_id"] == "777"
        assert "acordo homologado" in create_update.call_args.kwargs["body"]

    def test_should_not_post_analysis_update_when_board_has_analysis_column(self) -> None:
        with (
            patch.object(
                juridico_monday,
                "_load_juridico_board_context",
                return_value=_board_context(),
            ),
            patch.object(juridico_monday, "_find_existing_item_id", return_value=None),
            patch.object(juridico_monday, "_search_items_by_name", return_value=[]),
            patch.object(juridico_monday, "_create_item", return_value="777"),
            patch.object(juridico_monday, "_apply_complaint_column_values"),
            patch.object(juridico_monday, "_create_update") as create_update,
        ):
            result = register_providencia(
                intimacao=INTIMACAO,
                providencia=PROVIDENCIA,
                message_id="msg-001",
                analysis="Parecer do caso.",
                api_token="token-teste",
            )

        assert result is not None
        create_update.assert_not_called()

    def test_should_ignore_items_of_other_processes_or_unknown_names(self) -> None:
        existing = [
            {"id": "1", "name": "9999999-99.2026.8.26.0999 — Apresentar contestação"},
            {"id": "2", "name": "Item manual sem padrão"},
        ]
        with (
            patch.object(
                juridico_monday,
                "_load_juridico_board_context",
                return_value=_board_context(),
            ),
            patch.object(juridico_monday, "_find_existing_item_id", return_value=None),
            patch.object(juridico_monday, "_search_items_by_name", return_value=existing),
            patch.object(juridico_monday, "_create_item", return_value="3") as create_item,
            patch.object(juridico_monday, "_apply_complaint_column_values"),
        ):
            result = register_providencia(
                intimacao=INTIMACAO,
                providencia=PROVIDENCIA,
                message_id="msg-001",
                api_token="token-teste",
            )

        assert result is not None
        assert result.skipped_duplicate is False
        create_item.assert_called_once()


class TestRegisterAudiencia:
    def test_should_return_none_when_there_is_no_hearing(self) -> None:
        result = register_audiencia(
            intimacao=INTIMACAO,
            providencia=PROVIDENCIA,  # sem hearing_datetime
            message_id="msg-001",
            api_token="token-teste",
        )
        assert result is None

    def test_should_create_item_in_audiencias_board_when_hearing_exists(self) -> None:
        providencia = Providencia(
            action_type=ACTION_COMPARECER_AUDIENCIA,
            description="Preparar e comparecer à audiência",
            requires_action=True,
            hearing_datetime=datetime(2026, 8, 5, 14, 30),
        )
        with (
            patch.object(
                juridico_monday,
                "_load_juridico_board_context",
                return_value=_board_context(),
            ) as load_context,
            patch.object(juridico_monday, "_find_existing_item_id", return_value=None),
            patch.object(juridico_monday, "_find_existing_item_id_by_name", return_value=None),
            patch.object(juridico_monday, "_create_item", return_value="888") as create_item,
            patch.object(juridico_monday, "_apply_complaint_column_values") as apply_values,
        ):
            result = register_audiencia(
                intimacao=INTIMACAO,
                providencia=providencia,
                message_id="msg-002",
                api_token="token-teste",
            )

        assert result is not None
        assert result.item_id == "888"
        assert load_context.call_args.kwargs["board_name"] == "audiencias"
        assert create_item.call_args.kwargs["item_name"] == (
            "1001234-56.2026.8.26.0100 — Audiência 05/08/2026 14:30"
        )
        applied = apply_values.call_args.kwargs["column_values"]
        assert applied["col_aud"] == {"date": "2026-08-05", "time": "14:30:00"}
