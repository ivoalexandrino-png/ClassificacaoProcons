"""Testes de casos Monday para elaboração."""

from classificacao_procons.monday.cases import _extract_case_from_item


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

    def test_should_skip_cases_with_existing_response_links(self) -> None:
        item = {
            "id": "102",
            "name": "ANA",
            "column_values": [
                {
                    "id": "docs",
                    "text": "Drive",
                    "value": '{"url":"https://drive.google.com/drive/folders/abc"}',
                },
                {
                    "id": "response",
                    "text": "https://drive.google.com/file/full/view",
                    "value": '{"url":"https://drive.google.com/file/full/view"}',
                },
            ],
        }
        column_lookup = {"docs": "docs_sac", "response": "response_full_url"}

        assert _extract_case_from_item(item, column_lookup=column_lookup) is None

    def test_should_include_case_with_response_links_when_ignore_flag(self) -> None:
        item = {
            "id": "102",
            "name": "ANA",
            "column_values": [
                {
                    "id": "docs",
                    "text": "Drive",
                    "value": '{"url":"https://drive.google.com/drive/folders/abc"}',
                },
                {
                    "id": "response",
                    "text": "https://drive.google.com/file/full/view",
                    "value": '{"url":"https://drive.google.com/file/full/view"}',
                },
            ],
        }
        column_lookup = {"docs": "docs_sac", "response": "response_full_url"}

        case = _extract_case_from_item(
            item,
            column_lookup=column_lookup,
            ignore_response_links=True,
        )

        assert case is not None
        assert case.item_id == "102"

    def test_should_include_responded_case_when_ignore_closed_status(self) -> None:
        item = {
            "id": "103",
            "name": "NATHALIA",
            "column_values": [
                {
                    "id": "docs",
                    "text": "Drive",
                    "value": '{"url":"https://drive.google.com/drive/folders/abc"}',
                },
                {"id": "status", "text": "Respondido", "value": None},
            ],
        }
        column_lookup = {"docs": "docs_sac", "status": "status"}

        case = _extract_case_from_item(
            item,
            column_lookup=column_lookup,
            ignore_closed_status=True,
        )

        assert case is not None
        assert case.item_id == "103"

    def test_should_skip_case_without_response_when_only_with_existing(self) -> None:
        item = {
            "id": "104",
            "name": "PENDENTE",
            "column_values": [
                {
                    "id": "docs",
                    "text": "Drive",
                    "value": '{"url":"https://drive.google.com/drive/folders/abc"}',
                },
            ],
        }
        column_lookup = {"docs": "docs_sac"}

        assert (
            _extract_case_from_item(
                item,
                column_lookup=column_lookup,
                only_with_existing_response=True,
            )
            is None
        )
