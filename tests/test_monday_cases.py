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
