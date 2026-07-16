"""Testes de casos Monday para elaboração."""

from unittest.mock import patch

from classificacao_procons.monday.cases import (
    _extract_case_from_item,
    fetch_case_by_item_id,
    list_cases_ready_for_elaboration,
)


class TestMondayCases:
    def test_should_extract_case_when_docs_sac_is_filled(self) -> None:
        item = {
            "id": "100",
            "name": "MARIA SILVA",
            "column_values": [
                {"id": "docs", "text": "Drive", "value": '{"url":"https://drive.google.com/drive/folders/abc"}'},
                {"id": "protocol", "text": "1653213/2026", "value": None},
                {"id": "status", "text": "Pendente", "value": None},
            ],
        }
        column_lookup = {
            "docs": "docs_sac",
            "protocol": "protocol_number",
            "status": "status",
        }

        case = _extract_case_from_item(item, column_lookup=column_lookup)

        assert case is not None
        assert case.item_id == "100"
        assert case.docs_sac_url.endswith("/abc")

    def test_should_extract_complaint_pdf_url_from_notificacao_column(self) -> None:
        item = {
            "id": "100",
            "name": "MARIA SILVA",
            "column_values": [
                {
                    "id": "docs",
                    "text": "Drive",
                    "value": '{"url":"https://drive.google.com/drive/folders/abc"}',
                },
                {
                    "id": "pdf",
                    "text": "PDF",
                    "value": '{"url":"https://drive.google.com/file/d/pdf-1/view"}',
                },
            ],
        }
        column_lookup = {
            "docs": "docs_sac",
            "pdf": "pdf_url",
        }

        case = _extract_case_from_item(item, column_lookup=column_lookup)

        assert case is not None
        assert case.complaint_pdf_url is not None
        assert "pdf-1" in case.complaint_pdf_url

    def test_should_skip_responded_cases(self) -> None:
        item = {
            "id": "101",
            "name": "JOAO",
            "column_values": [
                {"id": "docs", "text": "Drive", "value": '{"url":"https://drive.google.com/drive/folders/abc"}'},
                {"id": "status", "text": "Respondido", "value": None},
            ],
        }
        column_lookup = {"docs": "docs_sac", "status": "status"}

        assert _extract_case_from_item(item, column_lookup=column_lookup) is None

    @patch("classificacao_procons.monday.cases._graphql_request")
    @patch("classificacao_procons.monday.cases.load_board_metadata")
    def test_should_list_only_pending_response_group(
        self,
        load_board_mock,
        graphql_mock,
    ) -> None:
        from classificacao_procons.monday.client import MondayBoardContext
        from classificacao_procons.monday.mapping import MondayColumn

        load_board_mock.return_value = MondayBoardContext(
            board_id="board-1",
            group_id="",
            columns=[
                MondayColumn("docs", "Docs SAC", "link"),
                MondayColumn("status", "Status", "status"),
            ],
            column_details=[],
            account_slug="b4a",
        )
        graphql_mock.side_effect = [
            {"boards": [{"groups": [
                {"id": "grp-old", "title": "2025"},
                {"id": "grp-pending", "title": "pendentes de resposta"},
            ]}]},
            {
                "boards": [
                    {
                        "groups": [
                            {
                                "items_page": {
                                    "cursor": None,
                                    "items": [
                                        {
                                            "id": "2",
                                            "name": "COM SAC",
                                            "column_values": [
                                                {
                                                    "id": "docs",
                                                    "text": "Drive",
                                                    "value": '{"url":"https://drive.google.com/drive/folders/abc"}',
                                                },
                                                {"id": "status", "text": "Pendente", "value": None},
                                            ],
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                ],
            },
        ]

        cases = list_cases_ready_for_elaboration(
            api_token="token",
            limit=10,
            page_size=10,
            max_items_scanned=10,
        )

        assert len(cases) == 1
        assert cases[0].item_id == "2"
        assert graphql_mock.call_count == 2
        group_query = graphql_mock.call_args_list[1].kwargs["variables"]
        assert group_query["groupId"] == "grp-pending"

    @patch("classificacao_procons.monday.cases._graphql_request")
    @patch("classificacao_procons.monday.cases.load_board_metadata")
    def test_should_fetch_case_by_item_id(self, load_board_mock, graphql_mock) -> None:
        from classificacao_procons.monday.client import MondayBoardContext
        from classificacao_procons.monday.mapping import MondayColumn

        load_board_mock.return_value = MondayBoardContext(
            board_id="board-1",
            group_id="",
            columns=[MondayColumn("docs", "Docs SAC", "link")],
            column_details=[],
            account_slug="b4a",
        )
        graphql_mock.return_value = {
            "items": [
                {
                    "id": "999",
                    "name": "ANTIGA",
                    "column_values": [
                        {
                            "id": "docs",
                            "text": "Drive",
                            "value": '{"url":"https://drive.google.com/drive/folders/legacy"}',
                        },
                    ],
                },
            ],
        }

        case = fetch_case_by_item_id(api_token="token", item_id="999")

        assert case is not None
        assert case.item_id == "999"
        assert case.docs_sac_url.endswith("/legacy")
